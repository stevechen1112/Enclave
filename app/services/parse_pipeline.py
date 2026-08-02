"""Phase 2 — Parse pipeline orchestrating native + RAGFlow paths."""
from __future__ import annotations

import hashlib
import logging
import os
import time
import asyncio
from typing import Any, Dict, List, Tuple
from uuid import UUID

from app.schemas.parse_artifact import ParseArtifact, ParseChunk
from app.services.parse_router import ParseRoute, classify_document
from app.services.document_parser import DocumentParser
from app.services.content_reference import build_content_reference, resolve_content_bytes

logger = logging.getLogger(__name__)


def _content_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return f"sha256:{h.hexdigest()}"


# RAGFlow's layout_recognize values map onto the engine label we are allowed to claim.
# "Plain Text" bypasses OCR/layout/TSR entirely, so it must never be labelled deepdoc.
_LAYOUT_ENGINE_MAP = {
    "deepdoc": ("ragflow/deepdoc", True),
    "plain text": ("ragflow/plaintext", False),
    "plaintext": ("ragflow/plaintext", False),
}


def _engine_label_for_layout(layout_recognize: Any) -> Tuple[str, bool]:
    """Return (engine_label, ocr_capable) for an upstream layout_recognize value."""
    if not layout_recognize:
        return "ragflow/unknown", False
    key = str(layout_recognize).strip().lower()
    if key in _LAYOUT_ENGINE_MAP:
        return _LAYOUT_ENGINE_MAP[key]
    # Vision-model layouts are named after the model; treat them as OCR-capable.
    return f"ragflow/{key.replace(' ', '_')}", True


async def _parse_via_ragflow(
    file_path: str,
    file_type: str,
    document_id: UUID,
    revision: int,
    content_hash: str,
    route: ParseRoute,
) -> ParseArtifact:
    from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
    from app.core.authorization import AuthorizationContext

    adapter = RAGFlowHTTPAdapter(
        base_url=os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380"),
        api_key=os.getenv("RAGFLOW_API_KEY", ""),
    )
    authz = AuthorizationContext(
        tenant_id=UUID(int=0),
        subject_id=UUID(int=1),
        is_superuser=True,
    )
    start = time.time()
    content_ref, ref_meta = build_content_reference(file_path, UUID(int=0), document_id)
    file_bytes = resolve_content_bytes(content_ref, ref_meta)
    result = await adapter.ingest(
        document_id=document_id,
        revision=revision,
        content_uri=content_ref,
        content_hash=content_hash,
        file_type=file_type,
        authz=authz,
        metadata={
            "dataset_id": os.getenv("RAGFLOW_DATASET_ID", ""),
            "ocr": route == ParseRoute.RAGFLOW_DEEPDOC,
            "vlm": route == ParseRoute.RAGFLOW_VLM,
            "file_path": file_path,
            "file_bytes": file_bytes,
        },
    )
    elapsed_ms = int((time.time() - start) * 1000)
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "ragflow ingest failed"))

    ragflow_doc_ids = result.get("ragflow_doc_ids") or []
    job_id = result.get("job_id") or (ragflow_doc_ids[0] if ragflow_doc_ids else "pending")

    parse_result: Dict[str, Any] = {"chunks": [], "confidence": 0.5}
    for attempt in range(12):
        parse_result = await adapter.get_parse_result(job_id)
        if parse_result.get("status") == "completed" and parse_result.get("chunks"):
            break
        if parse_result.get("status") == "error":
            break
        await asyncio.sleep(5)
    chunks = []
    for i, c in enumerate(parse_result.get("chunks", [])):
        bbox_raw = c.get("bbox")
        bbox = None
        if isinstance(bbox_raw, dict):
            from app.schemas.parse_artifact import BBox
            bbox = BBox(
                x=float(bbox_raw.get("x", 0)),
                y=float(bbox_raw.get("y", 0)),
                w=float(bbox_raw.get("w", bbox_raw.get("width", 0))),
                h=float(bbox_raw.get("h", bbox_raw.get("height", 0))),
            )
        chunks.append(
            ParseChunk(
                text=c.get("text", ""),
                template=c.get("template", "general"),
                chunk_index=i,
                page=c.get("page") or c.get("page_num"),
                bbox=bbox,
                hierarchy=c.get("hierarchy") or [],
            )
        )
    # Label by what RAGFlow actually ran. The dataset's layout_recognize is the only
    # source of truth; the Enclave route only expresses intent.
    dataset_config = await adapter.get_dataset_config()
    layout_actual = dataset_config.get("layout_recognize") if dataset_config.get("status") == "ok" else None
    engine_label, layout_ocr_capable = _engine_label_for_layout(layout_actual)

    warnings = list(parse_result.get("warnings") or [])
    if dataset_config.get("status") != "ok":
        warnings.append(f"ragflow_dataset_config_unavailable:{dataset_config.get('error')}")

    if not chunks:
        # RAGFlow produced nothing usable; the text below comes from the native parser,
        # so the artifact must be labelled native rather than claiming a RAGFlow parse.
        text, _meta = DocumentParser.parse(file_path, file_type)
        chunks = [ParseChunk(text=text[:8000], chunk_index=0)]
        engine_label = "native/text_fallback"
        ocr_used = False
        confidence = float(parse_result.get("confidence", 0.5))
        warnings.append("ragflow_chunks_empty_used_text_fallback")
    else:
        ocr_used = layout_ocr_capable
        confidence = float(parse_result.get("confidence", 0.9))

    parse_result = {**parse_result, "warnings": warnings}

    return ParseArtifact(
        parser=engine_label,
        version=adapter.version,
        source_hash=content_hash,
        document_id=str(document_id),
        document_revision=revision,
        chunks=chunks,
        confidence=confidence,
        elapsed_ms=elapsed_ms,
        ocr_used=ocr_used,
        vlm_used=route == ParseRoute.RAGFLOW_VLM and engine_label.startswith("ragflow/"),
        warnings=warnings,
        provider="ragflow",
        provider_resource_ids=[str(x) for x in ragflow_doc_ids if x],
        metadata={
            "layout_recognize_actual": layout_actual,
            "chunk_method_actual": dataset_config.get("chunk_method"),
            "parse_route_intent": route.value,
        },
    )


def _maybe_enhance_with_cloud_ocr(
    file_path: str,
    file_type: str,
    text: str,
    metadata: Dict[str, Any],
    artifact: ParseArtifact,
) -> Tuple[str, Dict[str, Any], ParseArtifact]:
    """Cloud OCR enhancement arm (CV-RF-01b): when the primary parser yields
    near-zero text on a scanned PDF/image, re-transcribe via the configured
    cloud OCR provider. Adopts the cloud result only when it yields strictly
    more text; the original engine is recorded in metadata either way."""
    from app.services import cloud_ocr

    ext = (file_type or "").lower().strip()
    if not cloud_ocr.is_enabled() or ext not in cloud_ocr.SUPPORTED_EXTS:
        return text, metadata, artifact
    trigger = int(os.getenv("CLOUD_OCR_TRIGGER_MIN_CHARS", "200"))
    if len((text or "").strip()) >= trigger:
        return text, metadata, artifact

    original_engine = artifact.parser
    try:
        result = cloud_ocr.transcribe(file_path, ext)
    except Exception as exc:
        artifact.warnings.append({"code": "cloud_ocr_failed", "error": str(exc)[:200]})
        return text, metadata, artifact

    metadata["cloud_ocr"] = {
        "provider": result.provider,
        "model": result.model,
        "pages": result.pages,
        "elapsed_ms": result.elapsed_ms,
        "retries": result.retries,
        "errors": result.errors,
        "trigger": f"primary_yield_below_{trigger}_chars",
        "original_engine": original_engine,
    }
    if len(result.text.strip()) <= len((text or "").strip()):
        artifact.warnings.append({"code": "cloud_ocr_no_better_yield"})
        return text, metadata, artifact

    artifact.parser = f"cloud/{result.provider}:{result.model}"
    artifact.ocr_used = True
    artifact.chunks = [ParseChunk(text=result.text, chunk_index=0)]
    artifact.warnings.append({
        "code": "cloud_ocr_adopted",
        "original_engine": original_engine,
        "original_chars": len((text or "").strip()),
        "cloud_chars": len(result.text.strip()),
    })
    metadata["parse_engine"] = artifact.parser
    metadata["ocr_used"] = True
    return result.text, metadata, artifact


def parse_document(
    file_path: str,
    file_type: str,
    document_id: UUID,
    revision: int = 1,
) -> Tuple[str, Dict[str, Any], ParseArtifact]:
    """
    Parse document and return (text_content, metadata_dict, ParseArtifact).
    Falls back to native parser on RAGFlow failure — unless RAGFLOW_FORCE_PARSE=true.
    """
    content_hash = _content_hash(file_path)
    route = classify_document(file_path, file_type)
    start = time.time()
    force_ragflow = os.getenv("RAGFLOW_FORCE_PARSE", "").lower() == "true"

    if route in (ParseRoute.RAGFLOW_DEEPDOC, ParseRoute.RAGFLOW_VLM) and os.getenv("RAGFLOW_ENABLED", "").lower() == "true":
        try:
            import asyncio
            artifact = asyncio.run(
                _parse_via_ragflow(file_path, file_type, document_id, revision, content_hash, route)
            )
            text = "\n\n".join(c.text for c in artifact.chunks if c.text)
            metadata = {
                "parse_engine": artifact.parser,
                "parse_route": route.value,
                "quality_score": artifact.confidence,
                "ocr_used": artifact.ocr_used,
                "vlm_used": artifact.vlm_used,
                "content_hash": content_hash,
                "elapsed_ms": artifact.elapsed_ms,
                "ragflow_already_ingested": bool(artifact.provider_resource_ids),
                "ragflow_doc_ids": list(artifact.provider_resource_ids),
                "layout_recognize_actual": artifact.metadata.get("layout_recognize_actual"),
                "chunk_method_actual": artifact.metadata.get("chunk_method_actual"),
            }
            return _maybe_enhance_with_cloud_ocr(file_path, file_type, text, metadata, artifact)
        except Exception as exc:
            if force_ragflow:
                raise RuntimeError(f"RAGFlow parse required but failed: {exc}") from exc
            logger.warning("RAGFlow parse failed, fallback native: %s", exc)

    # Structured tables (xlsx/csv/xls) are intentionally routed to native even when
    # RAGFLOW_FORCE_PARSE / PARSER_CANARY=ragflow — do not treat that as a failure.
    if (
        force_ragflow
        and os.getenv("RAGFLOW_ENABLED", "").lower() == "true"
        and route not in (ParseRoute.NATIVE_STRUCTURED,)
    ):
        raise RuntimeError("RAGFLOW_FORCE_PARSE=true but document was not routed to RAGFlow")

    text_content, metadata = DocumentParser.parse(file_path, file_type)
    elapsed_ms = int((time.time() - start) * 1000)
    artifact = ParseArtifact(
        parser=metadata.get("parse_engine", "native"),
        version="1.0.0",
        source_hash=content_hash,
        document_id=str(document_id),
        document_revision=revision,
        chunks=[ParseChunk(text=text_content[:8000], chunk_index=0)],
        confidence=float(metadata.get("quality_score", 0.8)),
        elapsed_ms=elapsed_ms,
        ocr_used=bool(metadata.get("ocr_used", False)),
    )
    metadata["parse_route"] = ParseRoute.NATIVE_FAST.value
    metadata["content_hash"] = content_hash
    return _maybe_enhance_with_cloud_ocr(file_path, file_type, text_content, metadata, artifact)
