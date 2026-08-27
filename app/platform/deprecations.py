"""Single source of truth for compatibility surfaces and removal gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

_STAGES = {"observe", "warn", "disable", "remove"}


@dataclass(frozen=True)
class DeprecationSurface:
    key: str
    kind: str
    legacy_path: str
    replacement_path: str
    stage: str
    observation_started_at: date
    zero_traffic_days: int = 30
    path_prefix: bool = False

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
            raise ValueError(f"invalid deprecation stage: {self.stage}")
        if not self.legacy_path.startswith("/") or not self.replacement_path.startswith(
            "/"
        ):
            raise ValueError("deprecation paths must be absolute")
        if self.zero_traffic_days < 30:
            raise ValueError("legacy removal requires at least 30 zero-traffic days")

    @property
    def eligible_after(self) -> date:
        return self.observation_started_at + timedelta(days=self.zero_traffic_days)

    @property
    def is_disabled(self) -> bool:
        return self.stage in {"disable", "remove"}

    def matches(self, path: str) -> bool:
        normalized = str(path or "")
        if self.path_prefix:
            return normalized == self.legacy_path or normalized.startswith(
                f"{self.legacy_path}/"
            )
        return normalized == self.legacy_path

    def removal_eligible(
        self, *, last_used_at: datetime | None, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(UTC)
        if self.stage not in {"warn", "disable"} or now.date() < self.eligible_after:
            return False
        cutoff = now - timedelta(days=self.zero_traffic_days)
        return last_used_at is None or last_used_at < cutoff


_START = date(2026, 8, 26)
SURFACES: tuple[DeprecationSurface, ...] = (
    DeprecationSurface(
        "frontend.documents",
        "frontend_route",
        "/documents",
        "/knowledge/assets",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.connectors",
        "frontend_route",
        "/connectors",
        "/knowledge/sources",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.agent",
        "frontend_route",
        "/agent",
        "/knowledge/sources",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.agent_review",
        "frontend_route",
        "/agent/review",
        "/knowledge/review",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.agent_progress",
        "frontend_route",
        "/agent/progress",
        "/knowledge/review",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.kb_health",
        "frontend_route",
        "/kb-health",
        "/knowledge/quality",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.query_analytics",
        "frontend_route",
        "/query-analytics",
        "/governance/insights",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.audit",
        "frontend_route",
        "/audit",
        "/governance/audit",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.departments",
        "frontend_route",
        "/departments",
        "/governance/departments",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.company",
        "frontend_route",
        "/company",
        "/governance/organization",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.knowledge_compiler",
        "frontend_route",
        "/knowledge-compiler",
        "/system/modules",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.usage", "frontend_route", "/usage", "/me/usage", "observe", _START
    ),
    DeprecationSurface(
        "frontend.my_usage",
        "frontend_route",
        "/my-usage",
        "/me/usage",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.generate", "frontend_route", "/generate", "/create", "observe", _START
    ),
    DeprecationSurface(
        "frontend.reports",
        "frontend_route",
        "/reports",
        "/create/reports",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "frontend.report_detail",
        "frontend_route",
        "/reports/:id",
        "/create/reports/:id",
        "observe",
        _START,
    ),
    DeprecationSurface(
        "api.documents",
        "api_route",
        "/api/v1/documents",
        "/api/v1/knowledge/assets",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.audio",
        "api_route",
        "/api/v1/voice",
        "/api/v1/knowledge/assets",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.video",
        "api_route",
        "/api/v1/media/videos",
        "/api/v1/knowledge/assets",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.video_artifacts",
        "api_route",
        "/api/v1/media/video-artifacts",
        "/api/v1/knowledge/review-items",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.legacy_review",
        "api_route",
        "/api/v1/agent/review",
        "/api/v1/knowledge/review-items",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.mka.capture",
        "api_route",
        "/api/v1/knowledge-captures",
        "/api/v1/knowledge/assets",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.mka.knowhow",
        "api_route",
        "/api/v1/knowhow",
        "/api/v1/knowledge/review-items",
        "observe",
        _START,
        path_prefix=True,
    ),
    DeprecationSurface(
        "api.mka.modules",
        "api_route",
        "/api/v1/job-modules",
        "/api/v1/experience/bootstrap",
        "observe",
        _START,
        path_prefix=True,
    ),
)

SURFACE_BY_KEY = {surface.key: surface for surface in SURFACES}
if len(SURFACE_BY_KEY) != len(SURFACES):
    raise RuntimeError("duplicate deprecation surface key")


def get_deprecation_surface(key: str) -> DeprecationSurface | None:
    return SURFACE_BY_KEY.get(str(key or "").strip())


def match_api_surface(path: str) -> DeprecationSurface | None:
    matches = [
        surface
        for surface in SURFACES
        if surface.kind == "api_route" and surface.matches(path)
    ]
    return max(matches, key=lambda surface: len(surface.legacy_path), default=None)
