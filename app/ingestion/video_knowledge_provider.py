"""Approved video procedure contribution for core knowledge retrieval."""

from __future__ import annotations

import json

from app.platform.knowledge import (
    KnowledgeCandidate,
    KnowledgeContributionContext,
)


class ApprovedVideoProcedureProvider:
    provider_key = "core.video_procedure"
    provider_version = "1.0"
    capability_keys = ("knowledge.procedure.read",)

    def contribute(
        self, context: KnowledgeContributionContext
    ) -> list[KnowledgeCandidate]:
        if context.db is None or context.has_explicit_kb_revision_scope:
            return []
        from app.models.asset import (
            ArtifactReviewDecision,
            AssetRevision,
            DerivedArtifact,
            SourceAsset,
        )

        rows = (
            context.db.query(
                DerivedArtifact,
                AssetRevision,
                SourceAsset,
                ArtifactReviewDecision,
            )
            .join(
                AssetRevision,
                (AssetRevision.tenant_id == DerivedArtifact.tenant_id)
                & (AssetRevision.id == DerivedArtifact.asset_revision_id),
            )
            .join(
                SourceAsset,
                (SourceAsset.tenant_id == AssetRevision.tenant_id)
                & (SourceAsset.id == AssetRevision.asset_id),
            )
            .join(
                ArtifactReviewDecision,
                (ArtifactReviewDecision.tenant_id == DerivedArtifact.tenant_id)
                & (ArtifactReviewDecision.artifact_id == DerivedArtifact.id)
                & (
                    ArtifactReviewDecision.asset_revision_id
                    == DerivedArtifact.asset_revision_id
                ),
            )
            .filter(
                DerivedArtifact.tenant_id == context.authz.tenant_id,
                DerivedArtifact.artifact_kind == "procedure_candidate",
                DerivedArtifact.quality_state == "ready",
                SourceAsset.asset_kind == "video",
                SourceAsset.status == "active",
                SourceAsset.tombstoned_at.is_(None),
                ArtifactReviewDecision.decision == "approved",
            )
            .order_by(DerivedArtifact.created_at.desc())
            .limit(max(context.top_k * 10, 100))
            .all()
        )
        from app.services.asset_visibility import asset_access_allows

        candidates: list[KnowledgeCandidate] = []
        for artifact, revision, asset, decision in rows:
            if not asset_access_allows(context.db, asset, authz=context.authz):
                continue
            try:
                reviewed_projection = dict(decision.resolution_json or {}).get(
                    "published_procedure"
                )
                payload = (
                    dict(reviewed_projection)
                    if isinstance(reviewed_projection, dict)
                    else json.loads(artifact.content or "{}")
                )
            except json.JSONDecodeError:
                continue
            steps = list(payload.get("steps") or [])
            if not steps:
                continue
            content = "\n".join(
                [
                    f"[影片程序] {payload.get('title') or asset.title}",
                    str(payload.get("summary") or ""),
                    *[
                        f"{step.get('sequence', index)}. {step.get('text', '')}"
                        for index, step in enumerate(steps, start=1)
                    ],
                ]
            )
            candidates.append(
                KnowledgeCandidate(
                    id=f"video-procedure:{artifact.id}",
                    tenant_id=str(context.authz.tenant_id),
                    content=content,
                    score=0.86,
                    canonical_resource_type="procedure_candidate",
                    canonical_resource_id=str(artifact.id),
                    result_type="procedure",
                    title=str(payload.get("title") or asset.title),
                    provider="core_video",
                    provider_version=self.provider_version,
                    metadata={
                        "asset_id": str(asset.id),
                        "asset_revision_id": str(revision.id),
                        "artifact_type": "procedure_candidate",
                        "deep_link": f"/knowledge/videos/{asset.id}",
                        "steps": steps,
                        "governance_state": payload.get("governance_state"),
                        "authority_overrides": list(
                            payload.get("authority_overrides") or []
                        ),
                    },
                )
            )
            if len(candidates) >= context.top_k:
                break
        return candidates
