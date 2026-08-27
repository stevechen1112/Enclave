"""Descriptors for the existing document and long-interview processors."""

from app.platform.ingestion import IngestionRequest


def document_capabilities(asset_kind: str) -> tuple[str, ...]:
    capabilities = ["extract_text"]
    if asset_kind in {"document", "email", "web_page"}:
        capabilities.append("layout")
    if asset_kind in {"spreadsheet", "dataset"}:
        capabilities.append("table")
    if asset_kind == "image":
        capabilities.append("ocr")
    return tuple(capabilities)


class CoreDocumentIngestionAdapter:
    adapter_key = "core.document"
    adapter_version = "1.0"
    supported_asset_kinds = (
        "document",
        "spreadsheet",
        "image",
        "email",
        "web_page",
        "dataset",
        "external_record",
    )
    capability_keys = ("extract_text", "layout", "table", "ocr")
    execution_boundary = "local_or_governed_provider"
    priority = 100

    def accepts(self, request: IngestionRequest) -> bool:
        return bool(request.media_type and request.content_uri)


class LongInterviewAudioIngestionAdapter:
    adapter_key = "core.long_interview_audio"
    adapter_version = "1.0"
    supported_asset_kinds = ("audio",)
    capability_keys = ("transcribe", "timestamp", "terminology_correction")
    execution_boundary = "tenant_voice_policy"
    priority = 100

    def accepts(self, request: IngestionRequest) -> bool:
        return request.media_type.startswith(
            ("audio/", "application/vnd.enclave.audio")
        )


class CoreVideoIngestionAdapter:
    adapter_key = "core.video"
    adapter_version = "1.0"
    supported_asset_kinds = ("video",)
    capability_keys = (
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
    execution_boundary = "governed_media_worker"
    priority = 100

    def accepts(self, request: IngestionRequest) -> bool:
        return request.media_type.startswith("video/")
