from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.api.v1.endpoints.knowledge_assets import _AUDIO_TYPES, _VIDEO_EXTENSIONS
from app.api.v1.endpoints.video_assets import _VIDEO_TYPES
from app.main import app
from app.platform.intake import (
    AUDIO_MEDIA_TYPES,
    DOCUMENT_TYPE_MAP,
    VIDEO_MEDIA_TYPES,
    build_input_capability_contract,
    input_registry_sha256,
)
from app.schemas.input_capabilities import InputCapabilityResponse
from app.services.document_parser import SUPPORTED_FORMATS

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "artifacts" / "input" / "i0_input_contract_snapshot.json"


def _config(**overrides):
    values = {
        "MAX_FILE_SIZE": 50 * 1024 * 1024,
        "VIDEO_MAX_BYTES": 500 * 1024 * 1024,
        "VIDEO_MAX_SECONDS": 3600,
        "VIDEO_INGESTION_ENABLED": True,
        "VIDEO_ALLOWED_CODECS": "h264,hevc",
        "AUDIO_ALLOWED_CODECS": "mp3,aac,flac",
        "AUDIO_MAX_SECONDS": 14400,
        "MEDIA_PROXY_ENABLED": True,
        "VOICE_STT_ENABLED": False,
        "LLAMAPARSE_ENABLED": True,
        "LLAMAPARSE_API_KEY": "secret-must-not-leak",
        "CLAMAV_ENABLED": False,
        "STORAGE_BACKEND": "local",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_parser_and_media_routes_derive_from_one_registry():
    assert SUPPORTED_FORMATS == dict(DOCUMENT_TYPE_MAP)
    assert _AUDIO_TYPES == dict(AUDIO_MEDIA_TYPES)
    assert _VIDEO_EXTENSIONS == set(VIDEO_MEDIA_TYPES)
    assert _VIDEO_TYPES == dict(VIDEO_MEDIA_TYPES)


def test_input_contract_is_tenant_bound_versioned_and_truthful():
    payload = build_input_capability_contract(tenant_id="tenant-i0", config=_config())
    contract = InputCapabilityResponse.model_validate(payload)
    assert contract.contract_version == "input-capabilities.v1"
    assert contract.registry_sha256 == input_registry_sha256()
    assert contract.tenant_id == "tenant-i0"
    assert contract.policy.generic_resumable_upload is True
    assert contract.policy.resumable_part_size > 0
    assert contract.policy.resumable_max_parts >= 1
    assert contract.policy.video_allowed_codecs == ["h264", "hevc"]
    assert contract.policy.audio_allowed_codecs == ["mp3", "aac", "flac"]
    assert contract.policy.media_proxy_enabled is True
    assert len({item.extension for item in contract.formats}) == len(contract.formats)
    xlsx = next(item for item in contract.formats if item.extension == ".xlsx")
    assert xlsx.quality_gate["key"] == "xlsx-row-cell-v1"
    assert xlsx.quality_gate["min_content_accuracy"] == 1.0
    assert next(item for item in contract.formats if item.extension == ".mp4").quality_gate is None
    assert (
        next(
            item for item in contract.formats if item.extension == ".wav"
        ).processing_status
        == "disabled"
    )
    assert (
        next(item for item in contract.formats if item.extension == ".mp4").max_bytes
        == 500 * 1024 * 1024
    )
    assert next(
        item for item in contract.formats if item.extension == ".wav"
    ).max_duration_seconds == 14400
    assert "secret-must-not-leak" not in json.dumps(payload)


def test_format_capabilities_are_routable_by_declared_adapter():
    contract = InputCapabilityResponse.model_validate(
        build_input_capability_contract(
            tenant_id="tenant-i0", config=_config(VOICE_STT_ENABLED=True)
        )
    )
    adapters = contract.adapters
    for format_capability in contract.formats:
        candidates = [
            adapter
            for adapter in adapters
            if format_capability.asset_kind in adapter.asset_kinds
            and set(format_capability.capabilities).issubset(adapter.capabilities)
        ]
        assert candidates, format_capability.extension


def test_input_capability_route_is_in_public_api_inventory():
    assert "/api/v1/knowledge/input-capabilities" in app.openapi()["paths"]


def test_unified_intake_contract_exposes_i1_governance_fields():
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/knowledge/assets"]["post"]
    body_schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    if "$ref" in body_schema:
        body_schema = schema["components"]["schemas"][body_schema["$ref"].split("/")[-1]]
    assert {
        "idempotency_key",
        "department_id",
        "data_classification",
        "context_metadata",
    }.issubset(body_schema["properties"])


def test_i0_contract_snapshot_matches_runtime_registry():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    payload = build_input_capability_contract(tenant_id="tenant-i0", config=_config())
    grouped = {
        "document": list(DOCUMENT_TYPE_MAP),
        "audio": list(AUDIO_MEDIA_TYPES),
        "video": list(VIDEO_MEDIA_TYPES),
    }
    adapters = {
        adapter["key"]: adapter["capabilities"] for adapter in payload["adapters"]
    }
    assert snapshot["contract_version"] == payload["contract_version"]
    assert snapshot["registry_sha256"] == payload["registry_sha256"]
    assert snapshot["formats"] == grouped
    assert snapshot["adapters"] == adapters
    assert snapshot["provider_keys"] == [
        provider["key"] for provider in payload["providers"]
    ]
