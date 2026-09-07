"""Canonical per-capability outcomes and non-secret Input runtime identity.

Requested capabilities must never disappear behind a single job-level success.
Every requested key receives one explicit outcome: available, degraded,
not_applicable, or failed.  The payload is JSON-safe and can be persisted in
``IngestionJob.readiness`` without a schema migration.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
from typing import Any, Literal, cast

from app.services.release_metadata import get_release_metadata

CapabilityStatus = Literal["available", "degraded", "not_applicable", "failed"]
CAPABILITY_STATUSES = {"available", "degraded", "not_applicable", "failed"}


def package_version(distribution: str) -> str | None:
    """Return an installed Python distribution version without leaking config."""

    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def capability_result(
    status: CapabilityStatus,
    *,
    reason_code: str | None = None,
    artifact_count: int = 0,
    provider: str | None = None,
    provider_version: str | None = None,
    model: str | None = None,
    confidence_provider_supplied: bool | None = None,
    calibration_version: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one validated, stable capability outcome."""

    if status not in CAPABILITY_STATUSES:
        raise ValueError(f"invalid capability status: {status}")
    if status != "available" and not str(reason_code or "").strip():
        raise ValueError(f"{status} capability result requires a reason_code")
    if int(artifact_count) < 0:
        raise ValueError("artifact_count must be non-negative")
    return {
        "status": status,
        "reason_code": str(reason_code) if reason_code else None,
        "artifact_count": int(artifact_count),
        "provider": {
            "name": provider,
            "version": provider_version,
            "model": model,
            "confidence_provider_supplied": confidence_provider_supplied,
            "calibration_version": calibration_version,
        }
        if any(
            value is not None
            for value in (
                provider,
                provider_version,
                model,
                confidence_provider_supplied,
                calibration_version,
            )
        )
        else None,
        "details": dict(details or {}),
    }


def complete_capability_results(
    requested_capabilities: Iterable[str],
    observed: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return exactly one explicit result for every requested capability.

    Missing results fail closed in the persisted contract instead of raising and
    losing the whole processing result.  Extra keys raise because they indicate
    code/registry drift and must be corrected by the developer.
    """

    requested = tuple(dict.fromkeys(str(value) for value in requested_capabilities))
    requested_set = set(requested)
    extras = sorted(set(observed) - requested_set)
    if extras:
        raise ValueError(f"unrequested capability results: {extras}")
    results: dict[str, dict[str, Any]] = {}
    for capability in requested:
        raw_value = observed.get(capability)
        if not raw_value:
            results[capability] = capability_result(
                "failed", reason_code="capability_result_missing"
            )
            continue
        if not isinstance(raw_value, Mapping):
            raise ValueError(f"invalid result payload for {capability}")
        value = dict(raw_value)
        status = str(value.get("status") or "")
        if status not in CAPABILITY_STATUSES:
            raise ValueError(f"invalid status for {capability}: {status}")
        if status != "available" and not value.get("reason_code"):
            raise ValueError(f"missing reason_code for {capability}: {status}")
        provider_value = value.get("provider")
        if provider_value is not None and not isinstance(provider_value, Mapping):
            raise ValueError(f"invalid provider payload for {capability}")
        details = value.get("details")
        if details is not None and not isinstance(details, Mapping):
            raise ValueError(f"invalid details payload for {capability}")
        provider_data = dict(provider_value or {})
        supplied = provider_data.get("confidence_provider_supplied")
        if supplied is not None and not isinstance(supplied, bool):
            raise ValueError(f"invalid provider confidence flag for {capability}")
        try:
            results[capability] = capability_result(
                cast(CapabilityStatus, status),
                reason_code=(
                    str(value["reason_code"]) if value.get("reason_code") else None
                ),
                artifact_count=int(value.get("artifact_count") or 0),
                provider=(
                    str(provider_data["name"])
                    if provider_data.get("name") is not None
                    else None
                ),
                provider_version=(
                    str(provider_data["version"])
                    if provider_data.get("version") is not None
                    else None
                ),
                model=(
                    str(provider_data["model"])
                    if provider_data.get("model") is not None
                    else None
                ),
                confidence_provider_supplied=(
                    supplied if isinstance(supplied, bool) else None
                ),
                calibration_version=(
                    str(provider_data["calibration_version"])
                    if provider_data.get("calibration_version") is not None
                    else None
                ),
                details=dict(details or {}),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid result payload for {capability}") from exc
    return results


def _dependency_version(command: str, *arguments: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if not executable:
        return {"available": False, "version": None}
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
        )
        combined = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
        first_line = combined.splitlines()[0][:200] if combined else None
        return {
            "available": completed.returncode == 0,
            "version": first_line,
        }
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return {"available": False, "version": None}


def _native_dependency_versions() -> dict[str, dict[str, Any]]:
    """Probe native tools concurrently so failure persistence cannot stall serially."""

    commands = {
        "ffmpeg": ("ffmpeg", "-version"),
        "ffprobe": ("ffprobe", "-version"),
        "tesseract": ("tesseract", "--version"),
        "pdftotext": ("pdftotext", "-v"),
        "libreoffice": ("libreoffice", "--version"),
    }
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        futures = {
            name: executor.submit(_dependency_version, command, *arguments)
            for name, (command, *arguments) in commands.items()
        }
        return {name: futures[name].result() for name in commands}


@lru_cache(maxsize=1)
def _cached_input_runtime_identity() -> dict[str, Any]:
    """Build the process-local runtime identity once."""

    identity: dict[str, Any] = {
        "schema_version": "input-runtime.v1",
        "release": get_release_metadata(),
        "runtime": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "executable_family": "python",
            "byteorder": sys.byteorder,
        },
        "native_dependencies": _native_dependency_versions(),
        "python_dependencies": {
            name: package_version(name)
            for name in ("openai", "pytesseract", "pillow", "pypdf", "openpyxl")
        },
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    identity["identity_hash"] = hashlib.sha256(encoded).hexdigest()
    return identity


def input_runtime_identity() -> dict[str, Any]:
    """Return an isolated, non-secret identity for reproducible Input evidence."""

    return deepcopy(_cached_input_runtime_identity())


def readiness_with_capability_results(
    readiness: Mapping[str, Any],
    *,
    requested_capabilities: Iterable[str],
    observed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach complete capability and runtime truth to one job readiness record."""

    return {
        **dict(readiness),
        "capability_results_schema": "input-capability-results.v1",
        "capability_results": complete_capability_results(
            requested_capabilities, observed
        ),
        # ``input_runtime_identity`` already isolates the cached source object.
        "runtime_identity": input_runtime_identity(),
    }


def audio_capability_results(
    requested_capabilities: Iterable[str],
    *,
    transcript_count: int,
    audio_chunk_count: int,
    preview_ready: bool,
    provider: str,
    provider_version: str | None = None,
    model: str | None = None,
    confidence_provider_supplied: bool = False,
    calibration_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Describe the actual audio outcomes, including legitimate no-speech input."""

    provider_version = provider_version or (
        package_version("openai") if provider == "openai" else None
    )
    has_transcript = transcript_count > 0
    observed = {
        "resumable_upload": capability_result("available"),
        "background_progress": capability_result("available"),
        "partial_readiness": capability_result("available"),
        "transcribe": capability_result(
            "available" if has_transcript else "not_applicable",
            reason_code=None if has_transcript else "no_speech_detected",
            artifact_count=transcript_count,
            provider=provider,
            provider_version=provider_version,
            model=model,
            confidence_provider_supplied=confidence_provider_supplied,
            calibration_version=calibration_version or "unavailable",
        ),
        "timestamp": capability_result(
            "available" if has_transcript else "not_applicable",
            reason_code=None if has_transcript else "no_speech_detected",
            artifact_count=transcript_count,
        ),
        "terminology_correction": capability_result(
            "degraded",
            reason_code="terminology_correction_not_implemented",
        ),
    }
    requested = tuple(requested_capabilities)
    results = complete_capability_results(
        requested, {key: observed[key] for key in requested if key in observed}
    )
    if "background_progress" in results:
        results["background_progress"]["details"] = {
            "audio_chunk_count": audio_chunk_count,
            "preview_ready": preview_ready,
        }
    return results


def video_capability_results(
    requested_capabilities: Iterable[str],
    *,
    has_audio: bool,
    audio_chunk_count: int,
    transcript_count: int,
    keyframe_count: int,
    ocr_count: int,
    procedure_artifact_id: str | None,
    preview_ready: bool,
    capability_states: Mapping[str, str] | None,
    provider_failures: Iterable[Mapping[str, Any]] = (),
    stt_provider: str = "openai",
    stt_provider_version: str | None = None,
    stt_model: str | None = None,
    stt_confidence_provider_supplied: bool = False,
    stt_calibration_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Map video pipeline observations to the public four-state contract."""

    states = dict(capability_states or {})
    failures = list(provider_failures)
    has_transcript = transcript_count > 0
    has_keyframes = keyframe_count > 0
    provider_version = stt_provider_version or (
        package_version("openai") if stt_provider == "openai" else None
    )

    def understanding_result(key: str) -> dict[str, Any]:
        state = states.get(key, "unavailable")
        if state == "failed":
            relevant_failures = [
                item
                for item in failures
                if not item.get("capabilities") or key in item.get("capabilities", [])
            ]
            failed_providers = sorted(
                {str(item.get("provider") or "unknown") for item in relevant_failures}
            )
            return capability_result(
                "failed",
                reason_code="provider_failed",
                details={"failed_providers": failed_providers},
            )
        if state in {"unavailable", "unavailable_no_audio"}:
            return capability_result(
                "not_applicable",
                reason_code=(
                    "no_audio_track"
                    if state == "unavailable_no_audio"
                    else "no_evidence_detected"
                ),
            )
        if state == "insufficient_signal":
            return capability_result("degraded", reason_code="insufficient_signal")
        return capability_result("available", details={"internal_state": state})

    observed = {
        "resumable_upload": capability_result("available"),
        "background_progress": capability_result("available"),
        "partial_readiness": capability_result("available"),
        "browser_proxy": capability_result(
            "available" if preview_ready else "degraded",
            reason_code=None if preview_ready else "browser_proxy_disabled",
        ),
        "probe_metadata": capability_result("available", artifact_count=1),
        "demux_audio": capability_result(
            "available" if has_audio else "not_applicable",
            reason_code=None if has_audio else "no_audio_track",
            artifact_count=audio_chunk_count,
        ),
        "transcribe": capability_result(
            "available" if has_transcript else "not_applicable",
            reason_code=None
            if has_transcript
            else ("no_speech_detected" if has_audio else "no_audio_track"),
            artifact_count=transcript_count,
            provider=stt_provider,
            provider_version=provider_version,
            model=stt_model,
            confidence_provider_supplied=stt_confidence_provider_supplied,
            calibration_version=stt_calibration_version or "unavailable",
        ),
        "timestamp": capability_result(
            "available" if (has_transcript or has_keyframes) else "not_applicable",
            reason_code=None
            if (has_transcript or has_keyframes)
            else "no_timed_evidence",
            artifact_count=transcript_count + keyframe_count,
        ),
        "keyframe": capability_result(
            "available" if has_keyframes else "failed",
            reason_code=None if has_keyframes else "keyframe_extraction_empty",
            artifact_count=keyframe_count,
            provider="ffmpeg",
        ),
        "ocr": capability_result(
            "available" if ocr_count else "not_applicable",
            reason_code=None if ocr_count else "no_text_detected",
            artifact_count=ocr_count,
            provider="tesseract",
            provider_version=package_version("pytesseract"),
            confidence_provider_supplied=True if ocr_count else False,
            calibration_version=(
                "provider-native-uncalibrated" if ocr_count else "unavailable"
            ),
        ),
        "diarize": capability_result(
            "available"
            if states.get("speaker_diarization") == "available_upstream"
            else ("degraded" if has_transcript else "not_applicable"),
            reason_code=None
            if states.get("speaker_diarization") == "available_upstream"
            else (
                "speaker_labels_unavailable"
                if has_transcript
                else ("no_speech_detected" if has_audio else "no_audio_track")
            ),
            artifact_count=transcript_count,
            provider=stt_provider,
            provider_version=provider_version,
            model=stt_model,
        ),
        "scene_segment": understanding_result("scene_segmentation"),
        "action_candidate": understanding_result("action_event"),
        "equipment_state": understanding_result("equipment_state"),
        "audio_event": understanding_result("audio_anomaly"),
        "temporal_align": understanding_result("temporal_alignment"),
        "procedure_candidate": capability_result(
            "available" if procedure_artifact_id else "not_applicable",
            reason_code=None
            if procedure_artifact_id
            else "no_evidence_backed_procedure",
            artifact_count=1 if procedure_artifact_id else 0,
        ),
    }
    requested = tuple(requested_capabilities)
    return complete_capability_results(
        requested, {key: observed[key] for key in requested if key in observed}
    )


def document_capability_results(
    requested_capabilities: Iterable[str],
    *,
    content_chars: int,
    chunk_count: int,
    parse_engine: str,
    parser_version: str | None,
    ocr_used: bool,
    machine_readable_content: bool = True,
) -> dict[str, dict[str, Any]]:
    """Describe document outcomes without treating an empty extraction as success."""

    has_content = content_chars > 0 and chunk_count > 0
    extracted_content = has_content and machine_readable_content
    observed: dict[str, dict[str, Any]] = {
        "extract_text": capability_result(
            (
                "available"
                if extracted_content
                else "degraded"
                if has_content
                else "failed"
            ),
            reason_code=(
                None
                if extracted_content
                else "manual_description_required"
                if has_content
                else "no_usable_text_extracted"
            ),
            artifact_count=chunk_count if extracted_content else 0,
            provider=parse_engine,
            provider_version=parser_version,
        ),
        "layout": capability_result(
            "degraded" if has_content else "failed",
            reason_code=(
                "layout_fidelity_not_measured"
                if has_content
                else "no_layout_evidence_extracted"
            ),
            artifact_count=chunk_count,
            provider=parse_engine,
            provider_version=parser_version,
        ),
        "table": capability_result(
            "degraded" if has_content else "failed",
            reason_code=(
                "table_fidelity_not_measured"
                if has_content
                else "no_table_content_extracted"
            ),
            artifact_count=chunk_count,
            provider=parse_engine,
            provider_version=parser_version,
        ),
        "ocr": capability_result(
            "available" if ocr_used and extracted_content else "not_applicable",
            reason_code=None
            if ocr_used and extracted_content
            else "ocr_not_used_or_no_text_detected",
            artifact_count=chunk_count if ocr_used and extracted_content else 0,
            provider=parse_engine,
            provider_version=parser_version,
            confidence_provider_supplied=False,
            calibration_version="unavailable",
        ),
    }
    requested = tuple(requested_capabilities)
    return complete_capability_results(
        requested, {key: observed[key] for key in requested if key in observed}
    )
