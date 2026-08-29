"""Versioned, server-owned Input capability registry.

This module is deliberately free of domain-pack imports.  Parsers, upload
routes and the public capability API derive their format declarations from
this registry so that adding a parser cannot silently diverge from the intake
contract.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any

from app.services.input_quality import quality_gate_for

INPUT_CONTRACT_VERSION = "input-capabilities.v1"


@dataclass(frozen=True)
class InputFormatSpec:
    extension: str
    media_type: str
    parser_kind: str
    asset_kind: str
    capabilities: tuple[str, ...]
    evidence_state: str
    ui_default: bool = False


def _document(
    extension: str,
    media_type: str,
    parser_kind: str,
    *,
    asset_kind: str = "document",
    capabilities: tuple[str, ...] = ("extract_text", "layout"),
    evidence_state: str = "transitional",
    ui_default: bool = False,
) -> InputFormatSpec:
    return InputFormatSpec(
        extension=extension,
        media_type=media_type,
        parser_kind=parser_kind,
        asset_kind=asset_kind,
        capabilities=capabilities,
        evidence_state=evidence_state,
        ui_default=ui_default,
    )


DOCUMENT_FORMAT_SPECS = (
    _document(
        ".pdf",
        "application/pdf",
        "pdf",
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(".doc", "application/msword", "doc"),
    _document(
        ".txt",
        "text/plain",
        "txt",
        capabilities=("extract_text",),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        asset_kind="spreadsheet",
        capabilities=("extract_text", "table"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".xls",
        "application/vnd.ms-excel",
        "xls",
        asset_kind="spreadsheet",
        capabilities=("extract_text", "table"),
    ),
    _document(
        ".csv",
        "text/csv",
        "csv",
        asset_kind="spreadsheet",
        capabilities=("extract_text", "table"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(".html", "text/html", "html", asset_kind="web_page"),
    _document(".htm", "text/html", "html", asset_kind="web_page"),
    _document(
        ".md",
        "text/markdown",
        "markdown",
        capabilities=("extract_text",),
        evidence_state="internally_verified",
    ),
    _document(".markdown", "text/markdown", "markdown", capabilities=("extract_text",)),
    _document(".rtf", "application/rtf", "rtf"),
    _document(
        ".json",
        "application/json",
        "json",
        asset_kind="dataset",
        capabilities=("extract_text",),
    ),
    _document(
        ".jpg",
        "image/jpeg",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".jpeg",
        "image/jpeg",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".png",
        "image/png",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".tiff",
        "image/tiff",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(
        ".tif",
        "image/tiff",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
    ),
    _document(
        ".bmp",
        "image/bmp",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
    ),
    _document(
        ".webp",
        "image/webp",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
    ),
    _document(
        ".heic",
        "image/heic",
        "image",
        asset_kind="image",
        capabilities=("extract_text", "ocr"),
    ),
    _document(
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
        evidence_state="internally_verified",
        ui_default=True,
    ),
    _document(".ppt", "application/vnd.ms-powerpoint", "ppt"),
)

AUDIO_CAPABILITIES = (
    "resumable_upload",
    "background_progress",
    "partial_readiness",
    "transcribe",
    "timestamp",
    "terminology_correction",
)

AUDIO_FORMAT_SPECS = (
    InputFormatSpec(
        ".mp3",
        "audio/mpeg",
        "audio",
        "audio",
        AUDIO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".wav",
        "audio/wav",
        "audio",
        "audio",
        AUDIO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".m4a",
        "audio/mp4",
        "audio",
        "audio",
        AUDIO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".ogg",
        "audio/ogg",
        "audio",
        "audio",
        AUDIO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".flac",
        "audio/flac",
        "audio",
        "audio",
        AUDIO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
)

VIDEO_CAPABILITIES = (
    "resumable_upload",
    "background_progress",
    "partial_readiness",
    "browser_proxy",
    "probe_metadata",
    "demux_audio",
    "transcribe",
    "timestamp",
    "keyframe",
    "ocr",
    "diarize",
    "scene_segment",
    "action_candidate",
    "equipment_state",
    "audio_event",
    "temporal_align",
    "procedure_candidate",
)

VIDEO_FORMAT_SPECS = (
    InputFormatSpec(
        ".mp4",
        "video/mp4",
        "video",
        "video",
        VIDEO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".mov",
        "video/quicktime",
        "video",
        "video",
        VIDEO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".webm",
        "video/webm",
        "video",
        "video",
        VIDEO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
    InputFormatSpec(
        ".mkv",
        "video/x-matroska",
        "video",
        "video",
        VIDEO_CAPABILITIES,
        "environment_validation_pending",
        True,
    ),
)

ALL_FORMAT_SPECS = DOCUMENT_FORMAT_SPECS + AUDIO_FORMAT_SPECS + VIDEO_FORMAT_SPECS
if len({item.extension for item in ALL_FORMAT_SPECS}) != len(ALL_FORMAT_SPECS):
    raise RuntimeError("duplicate extension in Input capability registry")

DOCUMENT_TYPE_MAP = MappingProxyType(
    {item.extension: item.parser_kind for item in DOCUMENT_FORMAT_SPECS}
)
AUDIO_MEDIA_TYPES = MappingProxyType(
    {item.extension: item.media_type for item in AUDIO_FORMAT_SPECS}
)
VIDEO_MEDIA_TYPES = MappingProxyType(
    {item.extension: item.media_type for item in VIDEO_FORMAT_SPECS}
)

_SOURCE_SPECS = (
    {
        "key": "file_upload",
        "evidence_state": "internally_verified",
        "availability": "available",
        "limitations": [
            "live customer S3/R2/MinIO and physical weak-network certification is deployment-specific"
        ],
    },
    {
        "key": "url",
        "evidence_state": "transitional",
        "availability": "available",
        "limitations": ["dynamic and authenticated pages are not certified"],
    },
    {
        "key": "external_record",
        "evidence_state": "transitional",
        "availability": "available",
        "limitations": ["connector-specific cursor and ACL contracts are pending"],
    },
    {
        "key": "browser_capture",
        "evidence_state": "environment_validation_pending",
        "availability": "available",
        "limitations": [
            "physical-device lock-screen and app-switch validation is pending"
        ],
    },
    {
        "key": "nas_smb",
        "evidence_state": "environment_validation_pending",
        "availability": "configured_per_tenant",
        "limitations": [
            "customer-scale delta, rename, delete and ACL validation is pending"
        ],
    },
    {
        "key": "sharepoint",
        "evidence_state": "environment_validation_pending",
        "availability": "configured_per_tenant",
        "limitations": ["customer OAuth tenant certification is pending"],
    },
    {
        "key": "google_drive",
        "evidence_state": "environment_validation_pending",
        "availability": "configured_per_tenant",
        "limitations": ["customer OAuth tenant certification is pending"],
    },
    {
        "key": "email_mailbox",
        "evidence_state": "not_implemented",
        "availability": "unavailable",
        "limitations": ["mailbox connector and retention contract are not implemented"],
    },
)


def _declarative_registry() -> dict[str, Any]:
    return {
        "contract_version": INPUT_CONTRACT_VERSION,
        "formats": [asdict(item) for item in ALL_FORMAT_SPECS],
        "sources": deepcopy(_SOURCE_SPECS),
    }


def input_registry_sha256() -> str:
    encoded = json.dumps(
        _declarative_registry(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _provider_states(config: Any) -> list[dict[str, Any]]:
    try:
        from app.services import document_parser

        local_ocr = bool(getattr(document_parser, "_HAS_OCR", False))
        pdf_images = bool(getattr(document_parser, "_HAS_PDF2IMAGE", False))
    except Exception:
        local_ocr = False
        pdf_images = False

    llama_configured = bool(
        getattr(config, "LLAMAPARSE_ENABLED", False)
        and str(getattr(config, "LLAMAPARSE_API_KEY", "") or "").strip()
    )
    stt_enabled = bool(getattr(config, "VOICE_STT_ENABLED", False))
    video_enabled = bool(getattr(config, "VIDEO_INGESTION_ENABLED", False))
    malware_enabled = bool(getattr(config, "CLAMAV_ENABLED", False))
    local_ocr_ready = local_ocr and pdf_images
    return [
        {
            "key": "native_document",
            "status": "available",
            "runtime_verified": True,
            "detail": "built-in parsers are loaded in this API process",
        },
        {
            "key": "local_ocr",
            "status": "available" if local_ocr_ready else "degraded",
            "runtime_verified": True,
            "detail": (
                "local OCR and image conversion dependencies are present"
                if local_ocr and pdf_images
                else "one or more local OCR/image conversion dependencies are absent"
            ),
        },
        {
            "key": "llamaparse",
            "status": "configured" if llama_configured else "disabled",
            "runtime_verified": False,
            "detail": "configuration only; provider health is not probed by this endpoint",
        },
        {
            "key": "stt",
            "status": "configured" if stt_enabled else "disabled",
            "runtime_verified": False,
            "detail": "configuration only; provider health is not probed by this endpoint",
        },
        {
            "key": "video_worker",
            "status": "configured" if video_enabled else "disabled",
            "runtime_verified": False,
            "detail": "configuration only; worker codec/runtime health is not probed by this endpoint",
        },
        {
            "key": "malware_scan",
            "status": "configured" if malware_enabled else "disabled",
            "runtime_verified": False,
            "detail": (
                "configuration only; ClamAV health is checked during intake"
                if malware_enabled
                else "uploads are not malware-scanned in this deployment configuration"
            ),
        },
        {
            "key": "storage",
            "status": "configured",
            "runtime_verified": False,
            "detail": f"backend={getattr(config, 'STORAGE_BACKEND', 'unknown')}; health is not probed by this endpoint",
        },
    ]


def _document_format_status(
    spec: InputFormatSpec, *, config: Any
) -> tuple[str, list[str]]:
    try:
        from app.services import document_parser

        flags = {
            "openpyxl": bool(getattr(document_parser, "_HAS_OPENPYXL", False)),
            "ocr": bool(getattr(document_parser, "_HAS_OCR", False)),
            "pdf2image": bool(getattr(document_parser, "_HAS_PDF2IMAGE", False)),
            "rtf": bool(getattr(document_parser, "_HAS_RTF", False)),
            "pptx": bool(getattr(document_parser, "_HAS_PPTX", False)),
        }
    except Exception:
        flags = {
            "openpyxl": False,
            "ocr": False,
            "pdf2image": False,
            "rtf": False,
            "pptx": False,
        }
    llama_configured = bool(
        getattr(config, "LLAMAPARSE_ENABLED", False)
        and str(getattr(config, "LLAMAPARSE_API_KEY", "") or "").strip()
    )
    reasons: list[str] = []
    if (
        spec.extension == ".pdf"
        and not (flags["ocr"] and flags["pdf2image"])
        and not llama_configured
    ):
        reasons.append("scanned PDF OCR dependencies are not configured")
    elif (
        spec.extension == ".doc"
        and not llama_configured
        and not (shutil.which("antiword") or shutil.which("libreoffice"))
    ):
        reasons.append("legacy DOC converter is unavailable")
    elif spec.extension == ".xlsx" and not flags["openpyxl"] and not llama_configured:
        reasons.append("XLSX parser dependency is unavailable")
    elif spec.extension == ".xls" and not llama_configured:
        reasons.append("legacy XLS requires a certified provider path")
    elif spec.extension == ".rtf" and not flags["rtf"] and not llama_configured:
        reasons.append("RTF parser dependency is unavailable")
    elif (
        spec.extension in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
        and not flags["ocr"]
        and not llama_configured
    ):
        reasons.append("image OCR dependency is unavailable")
    elif spec.extension == ".heic":
        reasons.append("HEIC decoder/runtime is not certified")
    elif spec.extension == ".pptx" and not flags["pptx"] and not llama_configured:
        reasons.append("PPTX parser dependency is unavailable")
    elif (
        spec.extension == ".ppt"
        and not llama_configured
        and not shutil.which("libreoffice")
    ):
        reasons.append("legacy PPT converter is unavailable")
    return ("degraded" if reasons else "configured", reasons)


def build_input_capability_contract(
    *, tenant_id: str, config: Any | None = None
) -> dict[str, Any]:
    if config is None:
        from app.config import settings

        config = settings

    formats: list[dict[str, Any]] = []
    for spec in ALL_FORMAT_SPECS:
        if spec.asset_kind == "video":
            max_bytes = int(getattr(config, "VIDEO_MAX_BYTES", 0))
            max_duration_seconds = int(getattr(config, "VIDEO_MAX_SECONDS", 0))
            enabled = bool(getattr(config, "VIDEO_INGESTION_ENABLED", False))
        elif spec.asset_kind == "audio":
            max_bytes = int(getattr(config, "MAX_FILE_SIZE", 0))
            max_duration_seconds = int(getattr(config, "AUDIO_MAX_SECONDS", 0))
            enabled = True
        else:
            max_bytes = int(getattr(config, "MAX_FILE_SIZE", 0))
            max_duration_seconds = None
            enabled = True
        if spec.asset_kind == "audio" and not bool(
            getattr(config, "VOICE_STT_ENABLED", False)
        ):
            processing_status = "disabled"
            degradation_reasons = ["STT is disabled in this deployment"]
        elif spec.asset_kind == "video" and not enabled:
            processing_status = "disabled"
            degradation_reasons = ["video ingestion is disabled in this deployment"]
        elif spec in DOCUMENT_FORMAT_SPECS:
            processing_status, degradation_reasons = _document_format_status(
                spec, config=config
            )
        else:
            processing_status = "configured"
            degradation_reasons = []
        formats.append(
            {
                **asdict(spec),
                "capabilities": list(spec.capabilities),
                "quality_gate": (
                    quality_gate_for(spec.extension).to_dict()
                    if spec in DOCUMENT_FORMAT_SPECS
                    else None
                ),
                "max_bytes": max_bytes,
                "max_duration_seconds": max_duration_seconds,
                "processing_status": processing_status,
                "degradation_reasons": degradation_reasons,
            }
        )

    from app.composition.ingestion import build_ingestion_adapter_registry

    registry = build_ingestion_adapter_registry()
    adapters = []
    for adapter in registry.adapters:
        adapters.append(
            {
                "key": adapter.adapter_key,
                "version": adapter.adapter_version,
                "asset_kinds": list(adapter.supported_asset_kinds),
                "capabilities": list(adapter.capability_keys),
                "execution_boundary": adapter.execution_boundary,
            }
        )

    return {
        "contract_version": INPUT_CONTRACT_VERSION,
        "registry_sha256": input_registry_sha256(),
        "tenant_id": str(tenant_id),
        "policy": {
            "scope": "deployment_with_tenant_identity",
            "accepted_modes": [
                "file",
                "source_url",
                "source_record_id",
                "capture_manifest",
            ],
            "data_classifications": [
                "public",
                "internal",
                "confidential",
                "restricted",
            ],
            "idempotency_key_max_chars": 500,
            "capture_manifest_max_bytes": 64 * 1024,
            "core_capture": True,
            "capture_modes": ["long_audio", "photo", "video"],
            "capture_policy_path": "/api/v1/knowledge/captures/policy",
            "generic_resumable_upload": True,
            "resumable_part_size": int(getattr(config, "UPLOAD_SESSION_PART_SIZE", 8 * 1024 * 1024)),
            "resumable_min_part_size": int(getattr(config, "UPLOAD_SESSION_MIN_PART_SIZE", 5 * 1024 * 1024)),
            "resumable_max_part_size": int(getattr(config, "UPLOAD_SESSION_MAX_PART_SIZE", 16 * 1024 * 1024)),
            "resumable_max_parts": int(getattr(config, "UPLOAD_SESSION_MAX_PARTS", 10_000)),
            "resumable_session_ttl_hours": int(getattr(config, "UPLOAD_SESSION_TTL_HOURS", 24)),
            "video_allowed_codecs": [
                item.strip()
                for item in str(
                    getattr(config, "VIDEO_ALLOWED_CODECS", "") or ""
                ).split(",")
                if item.strip()
            ],
            "audio_allowed_codecs": [
                item.strip()
                for item in str(
                    getattr(config, "AUDIO_ALLOWED_CODECS", "") or ""
                ).split(",")
                if item.strip()
            ],
            "media_proxy_enabled": bool(
                getattr(config, "MEDIA_PROXY_ENABLED", False)
            ),
        },
        "formats": formats,
        "sources": deepcopy(_SOURCE_SPECS),
        "providers": _provider_states(config),
        "adapters": adapters,
    }
