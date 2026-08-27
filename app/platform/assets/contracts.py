"""Format-neutral contracts for source assets, artifacts and evidence spans.

These are intentionally persistence-agnostic.  They establish the vocabulary
used by future DB models and ingestion adapters while existing Document and MKA
tables continue to serve production traffic during incremental migration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import Enum
from types import MappingProxyType
from typing import Any

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
CONTRACT_SCHEMA_VERSION = "1.0"


class AssetKind(str, Enum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    EMAIL = "email"
    WEB_PAGE = "web_page"
    DATASET = "dataset"
    EXTERNAL_RECORD = "external_record"


class ArtifactKind(str, Enum):
    EXTRACTED_TEXT = "extracted_text"
    LAYOUT_PAGE = "layout_page"
    OCR_REGION = "ocr_region"
    TABLE = "table"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    KEYFRAME = "keyframe"
    VIDEO_SCENE = "video_scene"
    AUDIO_EVENT = "audio_event"
    PROCEDURE_CANDIDATE = "procedure_candidate"
    ENTITY_CANDIDATE = "entity_candidate"


class EvidenceLocatorKind(str, Enum):
    DOCUMENT = "document"
    TABLE = "table"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    EXTERNAL_RECORD = "external_record"


class CoordinateSpace(str, Enum):
    NORMALIZED = "normalized"
    PIXEL = "pixel"


def _require_text(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{name} is required")


def _require_hash(name: str, value: str) -> None:
    if not _SHA256_RE.fullmatch(str(value or "")):
        raise ValueError(f"{name} must be a SHA-256 hex digest")


def _validate_bbox(
    bbox: Mapping[str, float] | None, coordinate_space: CoordinateSpace | None
) -> None:
    if bbox is None:
        return
    required = {"x", "y", "w", "h"}
    if set(bbox) != required:
        raise ValueError("bbox must contain exactly x, y, w, h")
    try:
        values = {key: float(bbox[key]) for key in required}
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox values must be numeric") from exc
    if values["x"] < 0 or values["y"] < 0:
        raise ValueError("bbox x/y must be non-negative")
    if values["w"] <= 0 or values["h"] <= 0:
        raise ValueError("bbox w/h must be positive")
    if coordinate_space is None:
        raise ValueError("bbox requires coordinate_space")
    if coordinate_space == CoordinateSpace.NORMALIZED and any(
        value > 1 for value in values.values()
    ):
        raise ValueError("normalized bbox values must be between 0 and 1")


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _coerce_enum(name: str, value: Any, enum_type: type[Enum]) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        supported = ", ".join(str(member.value) for member in enum_type)
        raise ValueError(f"{name} must be one of: {supported}") from exc


def _contract_dict(instance: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields(instance):
        value = getattr(instance, item.name)
        if isinstance(value, Enum):
            value = value.value
        elif isinstance(value, Mapping):
            value = dict(value)
        elif isinstance(value, tuple) and value and hasattr(value[0], "to_dict"):
            value = [member.to_dict() for member in value]
        result[item.name] = value
    return result


@dataclass(frozen=True)
class SourceAsset:
    """Stable logical identity and governance envelope for an input source."""

    tenant_id: str
    asset_id: str
    asset_kind: AssetKind
    source_system: str = "upload"
    source_record_id: str | None = None
    data_classification: str = "internal"
    acl_reference: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "asset_kind", _coerce_enum("asset_kind", self.asset_kind, AssetKind)
        )
        _require_text("tenant_id", self.tenant_id)
        _require_text("asset_id", self.asset_id)
        _require_text("schema_version", self.schema_version)
        if self.source_system != "upload" and not self.source_record_id:
            raise ValueError("connector assets require source_record_id")
        object.__setattr__(self, "acl_reference", _freeze_mapping(self.acl_reference))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _contract_dict(self)


@dataclass(frozen=True)
class AssetRevision:
    """Immutable bytes and media identity for one logical asset revision."""

    tenant_id: str
    asset_id: str
    revision: int
    media_type: str
    content_uri: str
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text("tenant_id", self.tenant_id)
        _require_text("asset_id", self.asset_id)
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if "/" not in self.media_type:
            raise ValueError("media_type must be a MIME type")
        _require_text("content_uri", self.content_uri)
        _require_hash("content_hash", self.content_hash)
        _require_text("schema_version", self.schema_version)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _contract_dict(self)


@dataclass(frozen=True)
class SourceAssetRevision:
    """Compatibility envelope; new persistence keeps asset and revision separate."""

    tenant_id: str
    asset_id: str
    revision: int
    asset_kind: AssetKind
    media_type: str
    content_uri: str
    content_hash: str
    source_system: str = "upload"
    source_record_id: str | None = None
    data_classification: str = "internal"
    acl_reference: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "asset_kind", _coerce_enum("asset_kind", self.asset_kind, AssetKind)
        )
        _require_text("tenant_id", self.tenant_id)
        _require_text("asset_id", self.asset_id)
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if "/" not in self.media_type:
            raise ValueError("media_type must be a MIME type")
        _require_text("content_uri", self.content_uri)
        _require_hash("content_hash", self.content_hash)
        if self.source_system != "upload" and not self.source_record_id:
            raise ValueError("connector assets require source_record_id")
        _require_text("schema_version", self.schema_version)
        object.__setattr__(self, "acl_reference", _freeze_mapping(self.acl_reference))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _contract_dict(self)

    def split(self) -> tuple[SourceAsset, AssetRevision]:
        return (
            SourceAsset(
                tenant_id=self.tenant_id,
                asset_id=self.asset_id,
                asset_kind=self.asset_kind,
                source_system=self.source_system,
                source_record_id=self.source_record_id,
                data_classification=self.data_classification,
                acl_reference=self.acl_reference,
                metadata=self.metadata,
                schema_version=self.schema_version,
            ),
            AssetRevision(
                tenant_id=self.tenant_id,
                asset_id=self.asset_id,
                revision=self.revision,
                media_type=self.media_type,
                content_uri=self.content_uri,
                content_hash=self.content_hash,
                metadata=self.metadata,
                schema_version=self.schema_version,
            ),
        )


@dataclass(frozen=True)
class EvidenceSpan:
    asset_id: str
    asset_revision: int
    locator_kind: EvidenceLocatorKind
    page: int | None = None
    section: str | None = None
    bbox: Mapping[str, float] | None = None
    coordinate_space: CoordinateSpace | None = None
    worksheet: str | None = None
    table: str | None = None
    row: int | None = None
    column: str | None = None
    cell_range: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    frame_index: int | None = None
    track_id: str | None = None
    source_system: str | None = None
    source_record_id: str | None = None
    field_path: str | None = None
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "locator_kind",
            _coerce_enum("locator_kind", self.locator_kind, EvidenceLocatorKind),
        )
        if self.coordinate_space is not None:
            object.__setattr__(
                self,
                "coordinate_space",
                _coerce_enum(
                    "coordinate_space", self.coordinate_space, CoordinateSpace
                ),
            )
        _require_text("asset_id", self.asset_id)
        if self.asset_revision < 1:
            raise ValueError("asset_revision must be >= 1")
        _require_text("schema_version", self.schema_version)
        _validate_bbox(self.bbox, self.coordinate_space)
        if self.bbox is not None:
            object.__setattr__(self, "bbox", _freeze_mapping(self.bbox))
        if self.page is not None and self.page < 1:
            raise ValueError("page must be >= 1")
        if self.row is not None and self.row < 1:
            raise ValueError("row must be >= 1")
        if self.frame_index is not None and self.frame_index < 0:
            raise ValueError("frame_index must be >= 0")
        if self.start_ms is not None and self.start_ms < 0:
            raise ValueError("start_ms must be >= 0")
        if self.end_ms is not None and self.end_ms < 0:
            raise ValueError("end_ms must be >= 0")
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("start_ms and end_ms must be provided together")
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.end_ms <= self.start_ms
        ):
            raise ValueError("end_ms must be greater than start_ms")

        if self.locator_kind == EvidenceLocatorKind.DOCUMENT:
            if self.page is None and not self.section:
                raise ValueError("document evidence requires page or section")
        elif self.locator_kind == EvidenceLocatorKind.TABLE:
            if not self.worksheet and not self.table:
                raise ValueError("table evidence requires worksheet or table")
            if self.row is None and not self.column and not self.cell_range:
                raise ValueError("table evidence requires row, column, or cell_range")
        elif self.locator_kind == EvidenceLocatorKind.IMAGE:
            if self.bbox is None and not self.section:
                raise ValueError("image evidence requires bbox or region label")
        elif self.locator_kind == EvidenceLocatorKind.AUDIO:
            if self.start_ms is None:
                raise ValueError("audio evidence requires a time range")
        elif self.locator_kind == EvidenceLocatorKind.VIDEO:
            if self.start_ms is None and self.frame_index is None:
                raise ValueError("video evidence requires a time range or frame")
        elif self.locator_kind == EvidenceLocatorKind.EXTERNAL_RECORD and (
            not self.source_system or not self.source_record_id
        ):
            raise ValueError(
                "external record evidence requires source_system and source_record_id"
            )

    def to_dict(self) -> dict[str, Any]:
        return _contract_dict(self)

    def to_legacy_metadata(self) -> dict[str, Any]:
        """Bridge fields understood by the current Citation/Chat context."""
        data = self.to_dict()
        data.pop("locator_kind", None)
        data.pop("schema_version", None)
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class DerivedArtifact:
    tenant_id: str
    artifact_id: str
    asset_id: str
    asset_revision: int
    artifact_kind: ArtifactKind
    content_hash: str
    provider: str
    provider_version: str
    quality_state: str = "provisional"
    confidence: float | None = None
    content: str | None = None
    artifact_uri: str | None = None
    evidence: tuple[EvidenceSpan, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_kind",
            _coerce_enum("artifact_kind", self.artifact_kind, ArtifactKind),
        )
        _require_text("tenant_id", self.tenant_id)
        _require_text("artifact_id", self.artifact_id)
        _require_text("asset_id", self.asset_id)
        if self.asset_revision < 1:
            raise ValueError("asset_revision must be >= 1")
        _require_hash("content_hash", self.content_hash)
        _require_text("provider", self.provider)
        _require_text("provider_version", self.provider_version)
        if self.content is None and self.artifact_uri is None:
            raise ValueError("artifact requires content or artifact_uri")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.quality_state not in {
            "provisional",
            "review_required",
            "ready",
            "rejected",
        }:
            raise ValueError("unsupported quality_state")
        _require_text("schema_version", self.schema_version)
        object.__setattr__(self, "evidence", tuple(self.evidence or ()))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        for span in self.evidence:
            if (
                span.asset_id != self.asset_id
                or span.asset_revision != self.asset_revision
            ):
                raise ValueError("evidence must reference the artifact asset revision")

    def to_dict(self) -> dict[str, Any]:
        return _contract_dict(self)
