"""VISION Phase 2 — TraceRecorder：逐步臂／命中／拒答可觀測。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TraceStep:
    step: int
    arm: str
    query: str
    hit_count: int
    hit_titles: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalTraceView:
    steps: List[TraceStep] = field(default_factory=list)
    refusal: Optional[Dict[str, Any]] = None
    plan_version: str = ""
    intent: str = ""

    def add_step(
        self,
        *,
        arm: str,
        query: str,
        hit_count: int,
        hit_titles: Optional[List[str]] = None,
        error: str = "",
    ) -> None:
        self.steps.append(
            TraceStep(
                step=len(self.steps) + 1,
                arm=arm,
                query=query,
                hit_count=hit_count,
                hit_titles=list(hit_titles or [])[:8],
                error=error,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "refusal": self.refusal,
        }
