"""Read-only, tenant-scoped audit of Input parsing quality.

The audit deliberately separates receipt, processor completion, parse quality,
human-review load, and publication.  It never changes source or review state.
Run it with a tenant UUID and archive stdout as the immutable evidence snapshot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import and_  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.asset import (  # noqa: E402
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)
from app.models.ingestion import IngestionJob  # noqa: E402
from app.models.knowledge_unit import (  # noqa: E402
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.services.rls import apply_rls_context  # noqa: E402


HUMAN_CANDIDATE_KINDS = {
    "extracted_text",
    "ocr_region",
    "table",
    "transcript_segment",
    "audio_event",
    "action_event",
    "equipment_state",
    "procedure_candidate",
    "entity_candidate",
    "speaker_turn",
    "video_scene",
    "timeline_alignment",
}
STRUCTURAL_KINDS = {"speaker_turn", "video_scene", "timeline_alignment"}
TEXT_KINDS = {"extracted_text", "ocr_region", "table", "transcript_segment"}
CAPABILITY_ARTIFACT_KINDS = {
    "extract_text": {"extracted_text"},
    "ocr": {"ocr_region"},
    "transcribe": {"transcript_segment"},
    "browser_proxy": {"media_proxy"},
    "keyframe": {"keyframe"},
    "scene_segment": {"video_scene"},
    "temporal_align": {"timeline_alignment"},
    "procedure_candidate": {"procedure_candidate", "sop_conflict_report"},
}
LOW_CONFIDENCE = 0.8
_SIMPLIFIED_ONLY = set("这为与发关个从东丝业严丧临举义乌乐书买乱争于亏云亚产亩亲仅从仓仪们价众会伞伟传伤伦伪体余佣侠侣侦侧侨俩债倾偿儿党兰兴养兽冈册写军农决况冻净凉减凤击划刘则创删别剂剑劳势勋华协单卖卢卫却厂厅历厉压县参双变叙叶号叹听吴启员呛呜咏咙围园国图圆圣场坏块坚坛坜坝坟坠垄垒垦垫垭垮垱垲垴执扩扫扬扰抚抛抢护报担拟拢拣拥拦拧拨择挂挚挛挜挞挟挠挡挣挤挥捞损捡换据掳掴掷掸掺掼揽搀搁搂搅携摄摆摇摊撑撵撷撸撺擞攒敌敛数斋斩断无旧时旷显晋晒晓晔暂术朴机杀杂权条来杨极构枪柜标栈栋栏树样档桥桩梦检欢欧歼殁残殒毕毙气汇汉汤沟没沪泪泼泽洁洼浅浆浇浊测济浑浓涂涛涝涟涡涣涤润涨涩渊渐渔湾湿溃溅滚滞满滤滥滦滨滩潇潜澜濒灭灯灵灾灿炉点炼烁烂烛烟烦烧烫热爱爷牍牵犊状犷犹狈狞独狭狮狰狱猎猕猪猫献玛环现电画畅疗疟疡疬疮疯痈痉痒痨痪瘫瘾皑皱盘盗盖监盐矿码砖砚砾础硅硕确碍礼祷祸离秃种积称秽稳窃窍竞笔笋筛筹签简箩篓篮篱籁类粮紧纠红纤约级纪纬纯纲纳纵纷纸纹纺纽线练组细织终绍经绑结绕绘给络绝统绣继绩续绳维绵综绿缀缅缆缉缎缓编缘缚缝缩缴罢罗罚罴羁翘耸耻聋职联聪肃肤肠肾肿胀胁胆胜胶脉脏脑脚脱脸腊腻腾舰舱艳艺节芜芦苏苹范茧荐荆荡荣荤荧药莱莲获莹萝营萧萨葱蒋蓝蓟蔷蔼蕴薮衔补装袭见观规觅视览觉触誉计订讣议讯记讲讳讴讶许讹论讼讽设访诀证评诅识诈诉诊词译试诗诚话诞询该详语误说请诸诺读课谁调谅谈谋谍谎谏谱贝贞负贡财责贤败账货质贩贪贫购贮贯贴贵贷贸费贺贼贾赁赃资赊赋赌赏赔赖赚赛赞赠赵赶趋跃践跷跸轧轨轩转轮软轰轴轻载较辅辆辈辉辐辑输辞辩边辽达迁过迈运还进远违连迟适选递逻遗邮邻郑酝酱释鉴针钉钙钝钟钢钦钩钱钻铁铃铅铜铝铭银铺链销锁锄锅锈锋锐错锡锣锦键锻镇镜长门闭问闯闰闲间闵闷闸闹闻阁阅阀队阳阴阵阶际陆陈险随隐隶难雏雾静韦页顶项顺须顾顿颁颂预领颇颈频题颜额风飞饥饭饮饰饱饲饼馆馈马驳驻驼驾骂验骑骗骚骤鱼鲁鲜鸟鸡鸣鸥鸿鹤鹰麦黄齐齿龙龟")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _normalise_text(value: str) -> str:
    return "".join(re.findall(r"[\w\u3400-\u9fff]", value.casefold()))


def _confidence(values: list[float | None]) -> dict[str, Any]:
    known = [float(value) for value in values if value is not None and value > 0]
    return {
        "known_count": len(known),
        "unknown_count": sum(value is None for value in values),
        "zero_sentinel_count": sum(value == 0 for value in values),
        "below_0_8_count": sum(0 < float(value) < LOW_CONFIDENCE for value in values if value is not None),
        "min": round(min(known), 4) if known else None,
        "mean": round(mean(known), 4) if known else None,
        "max": round(max(known), 4) if known else None,
    }


def _span_metrics(
    artifacts: list[DerivedArtifact], spans_by_artifact: dict[UUID, list[EvidenceSpan]], duration_ms: int | None
) -> dict[str, Any]:
    spans = [span for artifact in artifacts for span in spans_by_artifact.get(artifact.id, [])]
    timed = [span for span in spans if span.start_ms is not None]
    last_end = max((int(span.end_ms or span.start_ms or 0) for span in timed), default=None)
    return {
        "artifact_count": len(artifacts),
        "evidence_span_count": len(spans),
        "artifacts_with_evidence": sum(bool(spans_by_artifact.get(artifact.id)) for artifact in artifacts),
        "first_start_ms": min((int(span.start_ms or 0) for span in timed), default=None),
        "last_end_ms": last_end,
        "timeline_reach_ratio": (
            round(last_end / duration_ms, 4) if last_end is not None and duration_ms else None
        ),
        "speaker_labeled_count": sum(bool(span.speaker) for span in timed),
    }


def _gate(status: str, observed: Any, threshold: str, detail: str) -> dict[str, Any]:
    return {"status": status, "observed": observed, "threshold": threshold, "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--expected-source-count", type=int)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        apply_rls_context(db, args.tenant_id)
        assets = (
            db.query(SourceAsset)
            .filter(SourceAsset.tenant_id == args.tenant_id, SourceAsset.tombstoned_at.is_(None))
            .order_by(SourceAsset.created_at.asc())
            .all()
        )
        revisions = (
            db.query(AssetRevision)
            .filter(AssetRevision.tenant_id == args.tenant_id, AssetRevision.asset_id.in_([row.id for row in assets]))
            .all()
            if assets
            else []
        )
        current_revisions = {
            row.asset_id: row
            for row in revisions
            if row.revision == next(asset.current_revision for asset in assets if asset.id == row.asset_id)
        }
        revision_ids = [row.id for row in current_revisions.values()]
        jobs = (
            db.query(IngestionJob)
            .filter(IngestionJob.tenant_id == args.tenant_id, IngestionJob.asset_revision_id.in_(revision_ids))
            .order_by(IngestionJob.created_at.desc())
            .all()
            if revision_ids
            else []
        )
        jobs_by_revision: dict[UUID, IngestionJob] = {}
        for job in jobs:
            jobs_by_revision.setdefault(job.asset_revision_id, job)
        artifacts = (
            db.query(DerivedArtifact)
            .filter(DerivedArtifact.tenant_id == args.tenant_id, DerivedArtifact.asset_revision_id.in_(revision_ids))
            .order_by(DerivedArtifact.created_at.asc())
            .all()
            if revision_ids
            else []
        )
        artifacts_by_revision: dict[UUID, list[DerivedArtifact]] = {}
        for artifact in artifacts:
            artifacts_by_revision.setdefault(artifact.asset_revision_id, []).append(artifact)
        artifact_ids = [row.id for row in artifacts]
        spans = (
            db.query(EvidenceSpan)
            .filter(EvidenceSpan.tenant_id == args.tenant_id, EvidenceSpan.artifact_id.in_(artifact_ids))
            .all()
            if artifact_ids
            else []
        )
        spans_by_artifact: dict[UUID, list[EvidenceSpan]] = {}
        for span in spans:
            spans_by_artifact.setdefault(span.artifact_id, []).append(span)
        decision_counts = Counter(
            row.asset_revision_id
            for row in db.query(ArtifactReviewDecision)
            .filter(ArtifactReviewDecision.tenant_id == args.tenant_id, ArtifactReviewDecision.asset_revision_id.in_(revision_ids))
            .all()
        ) if revision_ids else Counter()

        active_units = (
            db.query(KnowledgeUnitRecord)
            .join(KnowledgeUnitRevision, and_(
                KnowledgeUnitRevision.tenant_id == KnowledgeUnitRecord.tenant_id,
                KnowledgeUnitRevision.unit_id == KnowledgeUnitRecord.id,
                KnowledgeUnitRevision.revision == KnowledgeUnitRecord.current_revision,
            ))
            .join(KnowledgeUnitReleaseMembership, and_(
                KnowledgeUnitReleaseMembership.tenant_id == KnowledgeUnitRevision.tenant_id,
                KnowledgeUnitReleaseMembership.unit_revision_id == KnowledgeUnitRevision.id,
                KnowledgeUnitReleaseMembership.status == "active",
            ))
            .join(KnowledgeUnitRelease, and_(
                KnowledgeUnitRelease.tenant_id == KnowledgeUnitReleaseMembership.tenant_id,
                KnowledgeUnitRelease.id == KnowledgeUnitReleaseMembership.release_id,
                KnowledgeUnitRelease.status == "active",
            ))
            .filter(
                KnowledgeUnitRecord.tenant_id == args.tenant_id,
                KnowledgeUnitRecord.source_asset_id.in_([row.id for row in assets]),
                KnowledgeUnitRecord.status == "active",
                KnowledgeUnitRecord.tombstoned_at.is_(None),
                KnowledgeUnitRevision.quality_state == "ready",
            )
            .all()
            if assets
            else []
        )
        active_units_by_asset = Counter(row.source_asset_id for row in active_units)

    source_reports: list[dict[str, Any]] = []
    transcript_corpora: list[tuple[str, str]] = []
    for asset in assets:
        revision = current_revisions.get(asset.id)
        job = jobs_by_revision.get(revision.id) if revision else None
        rows = artifacts_by_revision.get(revision.id, []) if revision else []
        kinds = Counter(row.artifact_kind for row in rows)
        requested_capabilities = set(job.requested_capabilities or []) if job else set()
        expected = {
            kind
            for capability, artifact_kinds in CAPABILITY_ARTIFACT_KINDS.items()
            if capability in requested_capabilities
            for kind in artifact_kinds
        }
        missing_expected = sorted(expected - set(kinds))
        pending = [row for row in rows if row.quality_state == "review_required"]
        human_candidates = [row for row in pending if row.artifact_kind in HUMAN_CANDIDATE_KINDS]
        structural_pending = [row for row in pending if row.artifact_kind in STRUCTURAL_KINDS]
        missing_evidence = [
            str(row.id)
            for row in human_candidates
            if not spans_by_artifact.get(row.id)
        ]
        transcript = [row for row in rows if row.artifact_kind == "transcript_segment"]
        transcript.sort(key=lambda row: min(
            (int(span.start_ms or 0) for span in spans_by_artifact.get(row.id, [])), default=0
        ))
        transcript_text = " ".join((row.content or "").strip() for row in transcript if (row.content or "").strip())
        if transcript_text:
            transcript_corpora.append((asset.title, transcript_text))
        ocr = [row for row in rows if row.artifact_kind == "ocr_region"]
        procedures = [row for row in rows if row.artifact_kind == "procedure_candidate"]
        text_rows = [row for row in rows if row.artifact_kind in TEXT_KINDS]
        provider_failures = list((job.readiness or {}).get("provider_failures") or []) if job else []
        transcript_span = _span_metrics(transcript, spans_by_artifact, revision.duration_ms if revision else None)
        transcript_confidence = _confidence([row.confidence for row in transcript])
        ocr_confidence = _confidence([row.confidence for row in ocr])
        procedure_confidence = _confidence([row.confidence for row in procedures])
        simplified_count = sum(character in _SIMPLIFIED_ONLY for character in transcript_text)
        receipt_pass = bool(
            revision
            and revision.content_hash
            and revision.content_uri
            and (revision.byte_size is None or revision.byte_size > 0)
        )
        processor_pass = bool(
            job
            and job.status in {"ready", "review_required"}
            and not (job.error or {})
            and not missing_expected
            and not provider_failures
        )
        source_reports.append({
            "source_asset_id": str(asset.id),
            "title": asset.title,
            "asset_kind": asset.asset_kind,
            "source_status": asset.status,
            "revision": {
                "id": str(revision.id) if revision else None,
                "media_type": revision.media_type if revision else None,
                "byte_size": revision.byte_size if revision else None,
                "duration_ms": revision.duration_ms if revision else None,
                "ingestion_status": revision.ingestion_status if revision else None,
            },
            "job": {
                "status": job.status if job else None,
                "phase": job.phase if job else None,
                "quality_state": job.quality_state if job else None,
                "attempt": job.attempt if job else None,
                "error_present": bool(job and (job.error or {})),
                "provider_failures": provider_failures,
                "requested_capabilities": sorted(requested_capabilities),
                "created_at": _iso(job.created_at) if job else None,
                "completed_at": _iso(job.completed_at) if job else None,
            },
            "receipt_pass": receipt_pass,
            "processor_completeness_pass": processor_pass,
            "artifact_count": len(rows),
            "artifact_kinds": dict(sorted(kinds.items())),
            "missing_expected_kinds": missing_expected,
            "pending_human_candidate_count": len(human_candidates),
            "structural_artifacts_exposed_for_review": len(structural_pending),
            "candidate_evidence_coverage": round(
                (len(human_candidates) - len(missing_evidence)) / len(human_candidates), 4
            ) if human_candidates else 1.0,
            "candidate_ids_missing_evidence": missing_evidence,
            "empty_text_artifact_count": sum(not (row.content or "").strip() for row in text_rows),
            "duplicate_text_hash_count": len(text_rows) - len({row.content_hash for row in text_rows}),
            "transcript": {
                **transcript_span,
                "character_count": len(transcript_text),
                "confidence": transcript_confidence,
                "simplified_only_character_count": simplified_count,
            },
            "ocr": {
                "region_count": len(ocr),
                "character_count": sum(len((row.content or "").strip()) for row in ocr),
                "confidence": ocr_confidence,
            },
            "procedure_candidates": {
                "count": len(procedures),
                "confidence": procedure_confidence,
            },
            "review_decision_count": int(decision_counts[revision.id]) if revision else 0,
            "active_published_unit_count": int(active_units_by_asset[asset.id]),
        })

    similarities = []
    for index, (left_title, left_text) in enumerate(transcript_corpora):
        for right_title, right_text in transcript_corpora[index + 1 :]:
            score = SequenceMatcher(None, _normalise_text(left_text), _normalise_text(right_text)).ratio()
            if score >= 0.5:
                similarities.append({
                    "left": left_title,
                    "right": right_title,
                    "normalised_character_similarity": round(score, 4),
                })

    all_human = sum(row["pending_human_candidate_count"] for row in source_reports)
    missing_evidence_total = sum(len(row["candidate_ids_missing_evidence"]) for row in source_reports)
    min_ocr_mean = min(
        (row["ocr"]["confidence"]["mean"] for row in source_reports if row["ocr"]["confidence"]["mean"] is not None),
        default=None,
    )
    zero_confidence_total = sum(
        row["transcript"]["confidence"]["zero_sentinel_count"] for row in source_reports
    )
    structural_total = sum(row["structural_artifacts_exposed_for_review"] for row in source_reports)
    report = {
        "schema_version": "input-parse-quality-audit/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "tenant_id": str(args.tenant_id),
        "read_only": True,
        "scope": {
            "active_source_count": len(assets),
            "artifact_count": len(artifacts),
            "evidence_span_count": len(spans),
            "review_decision_count": sum(decision_counts.values()),
            "active_published_unit_count": len(active_units),
        },
        "gates": {
            "expected_source_count": _gate(
                "PASS" if args.expected_source_count is None or len(assets) == args.expected_source_count else "FAIL",
                len(assets),
                str(args.expected_source_count) if args.expected_source_count is not None else "recorded only",
                "All currently active tenant sources are included.",
            ),
            "receipt_integrity": _gate(
                "PASS" if all(row["receipt_pass"] for row in source_reports) else "FAIL",
                f"{sum(row['receipt_pass'] for row in source_reports)}/{len(source_reports)}",
                "100%",
                "Immutable revision identity and source bytes are present.",
            ),
            "processor_completeness": _gate(
                "PASS" if all(row["processor_completeness_pass"] for row in source_reports) else "FAIL",
                f"{sum(row['processor_completeness_pass'] for row in source_reports)}/{len(source_reports)}",
                "100%; no active error/provider failure; expected artifact families present",
                "This checks pipeline completeness, not semantic correctness.",
            ),
            "candidate_evidence_coverage": _gate(
                "PASS" if not all_human or missing_evidence_total == 0 else "FAIL",
                round((all_human - missing_evidence_total) / all_human, 4) if all_human else 1.0,
                "1.0 for every human-actionable candidate",
                f"{missing_evidence_total} human-facing candidates have no typed evidence span.",
            ),
            "confidence_semantics": _gate(
                "PASS" if zero_confidence_total == 0 else "FAIL",
                {"zero_sentinel_transcripts": zero_confidence_total},
                "unknown confidence must be null, never synthetic 0",
                "A zero sentinel is indistinguishable from a measured 0% confidence in the UI.",
            ),
            "ocr_quality_floor": _gate(
                "PASS" if min_ocr_mean is not None and min_ocr_mean >= 0.75 else "FAIL",
                min_ocr_mean,
                "each source mean >= 0.75; low-confidence regions require review",
                "Provider confidence is a triage signal, not ground-truth accuracy.",
            ),
            "review_workload_design": _gate(
                "PASS" if structural_total == 0 else "FAIL",
                {"structural_candidates_in_human_queue": structural_total},
                "0",
                "Scenes, speaker turns, and timeline alignment are internal structure, not publication decisions.",
            ),
            "semantic_accuracy": _gate(
                "NOT_EVALUATED",
                None,
                "representative ground truth + field-owner acceptance",
                "Backend heuristics cannot prove wording or legal meaning against the original without a reference transcript/OCR truth set.",
            ),
            "publication_and_ask": _gate(
                "NOT_RUN" if not active_units else "PARTIAL",
                {"active_units": len(active_units), "review_decisions": sum(decision_counts.values())},
                "publish each accepted source, retrieve it in Ask, and open the cited evidence",
                "This is the next journey gate after parse-quality acceptance.",
            ),
        },
        "source_reports": source_reports,
        "cross_source_transcript_similarity": similarities,
    }
    blocking = [
        key for key, value in report["gates"].items() if value["status"] == "FAIL"
    ]
    report["overall"] = {
        "status": "HOLD" if blocking else "PASS",
        "blocking_gates": blocking,
        "statement": "Receipt and processing completion do not by themselves prove parse quality or answer readiness.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))
    return 2 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
