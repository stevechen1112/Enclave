"""Canonical multimodal asset contracts."""

from app.platform.assets.access import AssetAccessPolicy
from app.platform.assets.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ArtifactKind,
    AssetKind,
    AssetRevision,
    CoordinateSpace,
    DerivedArtifact,
    EvidenceLocatorKind,
    EvidenceSpan,
    SourceAsset,
    SourceAssetRevision,
)

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ArtifactKind",
    "AssetAccessPolicy",
    "AssetKind",
    "AssetRevision",
    "CoordinateSpace",
    "DerivedArtifact",
    "EvidenceLocatorKind",
    "EvidenceSpan",
    "SourceAsset",
    "SourceAssetRevision",
]
