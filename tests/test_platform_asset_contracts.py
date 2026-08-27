from __future__ import annotations

import pytest

from app.platform.assets import (
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

SHA = "a" * 64


def test_video_asset_and_temporal_artifact_contract():
    asset = SourceAssetRevision(
        tenant_id="tenant-1",
        asset_id="asset-1",
        revision=1,
        asset_kind=AssetKind.VIDEO,
        media_type="video/mp4",
        content_uri="s3://tenant-1/assets/asset-1/r1.mp4",
        content_hash=f"sha256:{SHA}",
    )
    evidence = EvidenceSpan(
        asset_id=asset.asset_id,
        asset_revision=asset.revision,
        locator_kind=EvidenceLocatorKind.VIDEO,
        start_ms=402_000,
        end_ms=438_000,
        frame_index=12_060,
        bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        coordinate_space=CoordinateSpace.NORMALIZED,
    )
    artifact = DerivedArtifact(
        tenant_id=asset.tenant_id,
        artifact_id="artifact-1",
        asset_id=asset.asset_id,
        asset_revision=asset.revision,
        artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENT,
        content_hash=SHA,
        provider="test-asr",
        provider_version="1.0",
        confidence=0.93,
        content="先確認壓力歸零，再解除安全門鎖。",
        evidence=(evidence,),
    )

    assert artifact.evidence[0].to_legacy_metadata()["start_ms"] == 402_000
    assert asset.asset_kind is AssetKind.VIDEO
    source, revision = asset.split()
    assert isinstance(source, SourceAsset)
    assert isinstance(revision, AssetRevision)
    assert source.asset_id == revision.asset_id


def test_connector_asset_requires_source_record_id():
    with pytest.raises(ValueError, match="source_record_id"):
        SourceAssetRevision(
            tenant_id="tenant-1",
            asset_id="asset-1",
            revision=1,
            asset_kind=AssetKind.DOCUMENT,
            media_type="application/pdf",
            content_uri="s3://tenant-1/assets/asset-1/r1.pdf",
            content_hash=SHA,
            source_system="sharepoint",
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "asset_id": "asset-1",
                "asset_revision": 1,
                "locator_kind": EvidenceLocatorKind.AUDIO,
                "start_ms": 100,
                "end_ms": 100,
            },
            "greater",
        ),
        (
            {
                "asset_id": "asset-1",
                "asset_revision": 1,
                "locator_kind": EvidenceLocatorKind.VIDEO,
            },
            "time range or frame",
        ),
        (
            {
                "asset_id": "asset-1",
                "asset_revision": 1,
                "locator_kind": EvidenceLocatorKind.IMAGE,
                "bbox": {"x": 0, "y": 0, "w": 0, "h": 1},
                "coordinate_space": CoordinateSpace.NORMALIZED,
            },
            "positive",
        ),
    ],
)
def test_evidence_span_rejects_ambiguous_or_invalid_location(kwargs, message):
    with pytest.raises(ValueError, match=message):
        EvidenceSpan(**kwargs)


def test_evidence_requires_stable_asset_revision_and_coordinate_space():
    with pytest.raises(ValueError, match="asset_id"):
        EvidenceSpan(
            asset_id="",
            asset_revision=1,
            locator_kind=EvidenceLocatorKind.DOCUMENT,
            page=1,
        )
    with pytest.raises(ValueError, match="coordinate_space"):
        EvidenceSpan(
            asset_id="asset-1",
            asset_revision=1,
            locator_kind=EvidenceLocatorKind.IMAGE,
            bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        )


def test_artifact_rejects_evidence_from_another_revision():
    evidence = EvidenceSpan(
        asset_id="asset-1",
        asset_revision=2,
        locator_kind=EvidenceLocatorKind.AUDIO,
        start_ms=0,
        end_ms=100,
    )
    with pytest.raises(ValueError, match="artifact asset revision"):
        DerivedArtifact(
            tenant_id="tenant-1",
            artifact_id="artifact-1",
            asset_id="asset-1",
            asset_revision=1,
            artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENT,
            content_hash=SHA,
            provider="asr",
            provider_version="1.0",
            content="text",
            evidence=(evidence,),
        )


def test_json_enum_values_are_normalized_before_locator_validation():
    evidence = EvidenceSpan(
        asset_id="asset-1",
        asset_revision=1,
        locator_kind="video",  # type: ignore[arg-type]
        start_ms=0,
        end_ms=100,
    )
    asset = SourceAsset(
        tenant_id="tenant-1",
        asset_id="asset-1",
        asset_kind="video",  # type: ignore[arg-type]
    )

    assert evidence.locator_kind is EvidenceLocatorKind.VIDEO
    assert asset.asset_kind is AssetKind.VIDEO

    with pytest.raises(ValueError, match="time range or frame"):
        EvidenceSpan(
            asset_id="asset-1",
            asset_revision=1,
            locator_kind="video",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="coordinate_space must be one of"):
        EvidenceSpan(
            asset_id="asset-1",
            asset_revision=1,
            locator_kind="image",  # type: ignore[arg-type]
            bbox={"x": 0, "y": 0, "w": 1, "h": 1},
            coordinate_space="unknown",  # type: ignore[arg-type]
        )
