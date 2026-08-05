"""
P0-2：Eval Profile — 統一評測設定來源。

借鑑 OpenAI KR 的 YAML/報告 DX，統一描述：
- 題庫路徑
- corpus／manifest
- retrieval top-k
- metrics
- deterministic judge
- optional LLM review judge
- 門檻
- artifact path
- profile version／hash

目標：降低 20+ eval scripts 的操作分散，不是重寫所有評測。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# ── 預設路徑 ──
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "configs" / "eval_profiles"
GOLDEN_DIR = PROJECT_ROOT / "testdata" / "golden"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


@dataclass
class EvalProfile:
    """單一評測設定檔，描述一個 eval run 的所有可調參數。"""

    # ── 識別 ──
    name: str = ""
    version: str = "1.0"
    description: str = ""

    # ── 題庫 ──
    questions_file: str = ""  # 相對於 testdata/golden/ 的 YAML 路徑
    expanded_file: Optional[str] = None  # 額外合併的題庫
    questions_offset: int = 0
    questions_limit: Optional[int] = None

    # ── 語料 ──
    corpus_manifest: Optional[str] = None  # 相對於 artifacts/ 的 manifest 路徑
    annotation_dir: Optional[str] = None  # 相對於 testdata/golden/ 的 annotation 目錄

    # ── 檢索 ──
    retrieval_top_k: int = 5
    retrieval_mode: str = "hybrid"
    retrieval_min_score: float = 0.0
    rerank: bool = True

    # ── 指標與門檻 ──
    metrics: List[str] = field(default_factory=lambda: ["hit_at_k", "mrr", "answer_correctness"])
    thresholds: Dict[str, float] = field(default_factory=dict)
    # 常見門檻
    # hit_at_k_min: float = 0.85
    # mrr_min: float = 0.70
    # answer_correctness_min: float = 0.90
    # cer_max: float = 0.05
    # zero_chunk_max: float = 0.05
    # p95_ms: int = 3000

    # ── Judge ──
    judge_type: str = "deterministic"  # deterministic | llm_review | hybrid
    llm_judge_model: str = ""  # 空字串 = 不用 LLM judge
    llm_judge_mode: str = "review"  # review（不改 frozen 主分）| override

    # ── Artifact ──
    artifact_name: str = ""  # artifacts/<name>_last_run.json
    artifact_dir: str = "artifacts"

    # ── Hold-out 特徵 ──
    gt_frozen: bool = False
    gt_frozen_at: str = ""
    intent_frozen: bool = False
    anti_target_drawing: bool = False

    # ── 來源（記錄用）──
    source_file: str = ""

    @property
    def questions_path(self) -> Path:
        """題庫絕對路徑。"""
        return GOLDEN_DIR / self.questions_file

    @property
    def expanded_path(self) -> Optional[Path]:
        if self.expanded_file:
            return GOLDEN_DIR / self.expanded_file
        return None

    @property
    def artifact_path(self) -> Path:
        """Artifact 絕對路徑。"""
        return ARTIFACTS_DIR / f"{self.artifact_name}_last_run.json"

    @property
    def profile_hash(self) -> str:
        """Profile 內容的 hash，用於 artifact 追蹤。"""
        content = f"{self.name}:{self.version}:{self.questions_file}:{self.retrieval_top_k}:{self.metrics}:{self.thresholds}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "questions_file": self.questions_file,
            "expanded_file": self.expanded_file,
            "retrieval_top_k": self.retrieval_top_k,
            "retrieval_mode": self.retrieval_mode,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "judge_type": self.judge_type,
            "llm_judge_model": self.llm_judge_model,
            "artifact_name": self.artifact_name,
            "gt_frozen": self.gt_frozen,
            "gt_frozen_at": self.gt_frozen_at,
            "intent_frozen": self.intent_frozen,
            "anti_target_drawing": self.anti_target_drawing,
            "profile_hash": self.profile_hash,
        }


def load_profile(name: str, profiles_dir: Optional[Path] = None) -> EvalProfile:
    """從 YAML 載入 eval profile。

    Args:
        name: profile 名稱（不含 .yaml 副檔名），如 "z3_blind"
        profiles_dir: 自訂 profiles 目錄，預設為 configs/eval_profiles/

    Returns:
        EvalProfile dataclass
    """
    base_dir = profiles_dir or PROFILES_DIR
    profile_path = base_dir / f"{name}.yaml"

    if not profile_path.exists():
        raise FileNotFoundError(f"Eval profile not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    profile = EvalProfile(
        name=data.get("name", name),
        version=data.get("version", "1.0"),
        description=data.get("description", ""),
        questions_file=data.get("questions_file", ""),
        expanded_file=data.get("expanded_file"),
        questions_offset=data.get("questions_offset", 0),
        questions_limit=data.get("questions_limit"),
        corpus_manifest=data.get("corpus_manifest"),
        annotation_dir=data.get("annotation_dir"),
        retrieval_top_k=data.get("retrieval_top_k", 5),
        retrieval_mode=data.get("retrieval_mode", "hybrid"),
        retrieval_min_score=data.get("retrieval_min_score", 0.0),
        rerank=data.get("rerank", True),
        metrics=data.get("metrics", ["hit_at_k", "mrr", "answer_correctness"]),
        thresholds=data.get("thresholds", {}),
        judge_type=data.get("judge_type", "deterministic"),
        llm_judge_model=data.get("llm_judge_model", ""),
        llm_judge_mode=data.get("llm_judge_mode", "review"),
        artifact_name=data.get("artifact_name", name),
        artifact_dir=data.get("artifact_dir", "artifacts"),
        gt_frozen=data.get("gt_frozen", False),
        gt_frozen_at=data.get("gt_frozen_at", ""),
        intent_frozen=data.get("intent_frozen", False),
        anti_target_drawing=data.get("anti_target_drawing", False),
        source_file=str(profile_path),
    )

    logger.info(f"Loaded eval profile: {profile.name} (hash={profile.profile_hash})")
    return profile


def list_profiles(profiles_dir: Optional[Path] = None) -> List[str]:
    """列出所有可用的 eval profile 名稱。"""
    base_dir = profiles_dir or PROFILES_DIR
    if not base_dir.exists():
        return []
    return sorted([f.stem for f in base_dir.glob("*.yaml")])