"""TaskEngine — 職能任務平台的任務執行核心（Phase 2）。

- 版本化 TaskDefinition 解析（租戶覆寫優先，全域定義 fallback，取最新 enabled 版本）。
- TaskRun：idempotency、input snapshot、resolved context、field sources、provenance。
- 統一狀態機：draft → in_progress → waiting_review → approved/rejected → executed/exported/failed。
- typed handlers：每個任務型別一個 handler；未實作的型別明確 raise，不假裝成功。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.job_context import (
    EffectiveJobContext,
    ModuleAccessDenied,
    assert_module_access,
    build_effective_job_context,
)

if TYPE_CHECKING:
    from app.models.mka import TaskRun

logger = logging.getLogger(__name__)

# ── 統一狀態機 ────────────────────────────────────────────────────────────────

TASK_STATUS_TRANSITIONS: Dict[str, set] = {
    "draft": {"in_progress", "failed"},
    "in_progress": {"waiting_review", "executed", "failed"},
    "waiting_review": {"approved", "rejected", "failed"},
    "approved": {"executed", "exported", "failed"},
    "rejected": {"draft", "failed"},
    "executed": {"exported"},
    "exported": set(),
    "failed": {"draft"},
}

TERMINAL_STATUSES = {"exported"}


class TaskEngineError(Exception):
    """任務引擎一般錯誤（定義不存在、狀態非法等）。"""


class TaskAccessDenied(PermissionError):
    """任務存取被拒（能力／模組／職能不符）。"""


class TaskHandlerNotImplemented(TaskEngineError):
    """該任務型別的 handler 尚未實作 — 明確失敗，不假裝成功。"""


# ── Handler 契約 ─────────────────────────────────────────────────────────────

class TaskInvalidTransition(TaskEngineError):
    """The requested task state transition conflicts with the current state."""


@dataclass
class TaskRunContext:
    db: Session
    user: Any
    job_ctx: EffectiveJobContext
    run: Any  # TaskRun
    definition: Any  # TaskDefinition
    inputs: Dict[str, Any]


@dataclass
class TaskResult:
    output_refs: Dict[str, Any] = field(default_factory=dict)
    field_sources: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    next_status: str = "in_progress"


TaskHandler = Callable[[TaskRunContext], TaskResult]


# ── Engine ────────────────────────────────────────────────────────────────────

class TaskEngine:
    def __init__(self, db: Session):
        self.db = db

    def _emit(
        self,
        run: TaskRun,
        event_type: str,
        *,
        actor_id: Optional[UUID] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """寫入 TaskRun 事件（Phase 7 可觀測性）。"""
        from app.models.mka import TaskRunEvent

        self.db.add(TaskRunEvent(
            tenant_id=run.tenant_id,
            run_id=run.id,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload or {},
        ))

    # ── 定義解析 ──

    def resolve_definition(self, tenant_id: UUID, task_key: str):
        """租戶覆寫優先；全域（tenant_id NULL）fallback；取最新 enabled 版本。"""
        from app.platform.knowledge import is_legacy_ask_task

        if is_legacy_ask_task(task_key):
            return None
        from app.models.mka import TaskDefinition

        rows = (
            self.db.query(TaskDefinition)
            .filter(
                TaskDefinition.task_key == task_key,
                TaskDefinition.status == "enabled",
                (TaskDefinition.tenant_id == tenant_id)
                | (TaskDefinition.tenant_id.is_(None)),
            )
            .all()
        )
        if not rows:
            return None
        tenant_rows = [r for r in rows if r.tenant_id == tenant_id]
        candidates = tenant_rows or rows

        def _ver_key(r):
            try:
                return tuple(int(p) for p in str(r.version).split("."))
            except ValueError:
                return (0,)

        return max(candidates, key=_ver_key)

    def list_accessible_definitions(self, user: Any) -> List[Any]:
        """Return only effective task definitions the user can actually start.

        Task discovery and workspace navigation share this method so the UI
        cannot advertise an entry that the runtime will reject.
        """
        from app.models.mka import TaskDefinition

        rows = (
            self.db.query(TaskDefinition)
            .filter(
                TaskDefinition.status == "enabled",
                (TaskDefinition.tenant_id == user.tenant_id)
                | (TaskDefinition.tenant_id.is_(None)),
            )
            .all()
        )
        resolved: Dict[str, Any] = {}
        for row in rows:
            effective = self.resolve_definition(user.tenant_id, row.task_key)
            if effective is not None:
                resolved[row.task_key] = effective

        job_ctx = build_effective_job_context(self.db, user)
        accessible: List[Any] = []
        for definition in resolved.values():
            try:
                self._assert_task_access(definition, user, job_ctx)
            except TaskAccessDenied:
                continue
            accessible.append(definition)
        return accessible

    # ── 存取檢查 ──

    def _assert_task_access(
        self, definition: Any, user: Any, job_ctx: EffectiveJobContext
    ) -> None:
        # 1. 安全能力
        required = list(definition.required_capabilities or [])
        if required:
            from app.services.access_capabilities import capabilities_for_user

            caps = set(capabilities_for_user(user))
            # Domain workspace access is contextual, not a Base role grant.
            # The module ACL below remains authoritative and deny-first.
            if (
                definition.module_key
                and definition.module_key in job_ctx.active_module_keys
            ):
                caps.add("field_work")
            missing = [c for c in required if c not in caps]
            if missing:
                raise TaskAccessDenied(f"缺少能力：{missing}")

        # 2. 模組（含租戶 binding）
        if definition.module_key:
            try:
                assert_module_access(self.db, user, definition.module_key)
            except ModuleAccessDenied as exc:
                raise TaskAccessDenied(str(exc)) from exc

        # 3. 職能 allowlist
        allowed_job = list(definition.applicable_job_role_keys or [])
        if allowed_job and not any(
            k in allowed_job for k in job_ctx.active_job_role_keys
        ):
            raise TaskAccessDenied(
                f"任務 {definition.task_key} 不適用於目前職能"
            )

    # ── Run 生命週期 ──

    def start_run(
        self,
        *,
        user: Any,
        task_key: str,
        inputs: Optional[Dict[str, Any]] = None,
        idempotency_key: str,
        scene: Optional[Dict[str, Any]] = None,
    ):
        """建立 TaskRun（idempotent）。回傳 (run, created)。"""
        from app.models.mka import TaskRun

        existing = (
            self.db.query(TaskRun)
            .filter(
                TaskRun.tenant_id == user.tenant_id,
                TaskRun.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if existing.user_id != user.id:
                # 同租戶不同使用者撞 key：不回傳他人 run（含 input_snapshot／provenance）
                raise TaskAccessDenied("idempotency key 已被其他使用者使用")
            return existing, False

        definition = self.resolve_definition(user.tenant_id, task_key)
        if definition is None:
            raise TaskEngineError(f"任務定義不存在或未啟用：{task_key}")

        job_ctx = build_effective_job_context(self.db, user, scene=scene)
        self._assert_task_access(definition, user, job_ctx)

        run = TaskRun(
            tenant_id=user.tenant_id,
            task_definition_id=definition.id,
            task_key=definition.task_key,
            task_version=definition.version,
            idempotency_key=idempotency_key,
            user_id=user.id,
            job_role_id=(
                UUID(job_ctx.active_job_role.job_role_id)
                if job_ctx.active_job_role
                else None
            ),
            module_key=definition.module_key,
            status="draft",
            input_snapshot=dict(inputs or {}),
            resolved_context=job_ctx.to_dict(),
            field_sources={},
            provenance={"missing_fields": [], "manual_edits": []},
            output_refs={},
        )
        self.db.add(run)
        self.db.flush()
        self._emit(run, "run_created", actor_id=user.id,
                   payload={"task_key": definition.task_key,
                            "definition_version": definition.version})
        return run, True

    def transition(self, run: Any, to_status: str, *, error: Optional[Dict[str, Any]] = None) -> None:
        allowed = TASK_STATUS_TRANSITIONS.get(run.status, set())
        if to_status not in allowed:
            raise TaskInvalidTransition(
                f"非法狀態轉換：{run.status} → {to_status}"
            )
        from_status = run.status
        run.status = to_status
        if error is not None:
            run.error = error
        self.db.flush()
        self._emit(run, "transition", payload={"from": from_status, "to": to_status})
        if to_status == "failed":
            self._emit(run, "failed", payload=error or {})

    def fail(self, run: Any, *, code: str, message: str, retryable: bool = False) -> None:
        if run.status not in TASK_STATUS_TRANSITIONS or "failed" not in TASK_STATUS_TRANSITIONS.get(run.status, set()):
            # 終態不可再 fail
            raise TaskEngineError(f"狀態 {run.status} 不可標記失敗")
        self.transition(
            run, "failed",
            error={"code": code, "message": message, "retryable": retryable},
        )

    def record_field_sources(self, run: Any, sources: Dict[str, Dict[str, Any]]) -> None:
        """記錄欄位來源：{field: {source: voice|knowledge|tool|rule|user|default, ref, confidence}}。"""
        merged = dict(run.field_sources or {})
        merged.update(sources)
        run.field_sources = merged
        self.db.flush()
        self._emit(run, "field_sources_updated",
                   payload={"fields": sorted(sources.keys())})

    def record_manual_edit(self, run: Any, field_name: str) -> None:
        prov = dict(run.provenance or {})
        edits = list(prov.get("manual_edits") or [])
        if field_name not in edits:
            edits.append(field_name)
        prov["manual_edits"] = edits
        run.provenance = prov
        self.db.flush()
        self._emit(run, "manual_edit", payload={"field": field_name})

    # ── 執行 ──

    def execute(self, run: Any, user: Any) -> TaskResult:
        """執行 run 對應的 typed handler。"""
        from app.models.mka import TaskDefinition

        # Validate before invoking the handler.  Form/knowhow handlers persist
        # side effects, so checking only the eventual state transition is too
        # late and allows a repeated request to create duplicate records.
        if run.status not in {"draft", "in_progress"}:
            raise TaskInvalidTransition(f"任務狀態 {run.status} 不可重複執行")

        definition = (
            self.db.query(TaskDefinition)
            .filter(TaskDefinition.id == run.task_definition_id)
            .first()
        )
        if definition is None:
            raise TaskEngineError("任務定義已不存在")

        handler = TASK_HANDLERS.get(definition.handler_key)
        if handler is None:
            raise TaskHandlerNotImplemented(
                f"handler 未註冊：{definition.handler_key}"
            )

        job_ctx = build_effective_job_context(self.db, user)
        ctx = TaskRunContext(
            db=self.db,
            user=user,
            job_ctx=job_ctx,
            run=run,
            definition=definition,
            inputs=dict(run.input_snapshot or {}),
        )
        if run.status == "draft":
            self.transition(run, "in_progress")
        result = handler(ctx)

        if result.output_refs:
            merged = dict(run.output_refs or {})
            merged.update(result.output_refs)
            run.output_refs = merged
        if result.field_sources:
            self.record_field_sources(run, result.field_sources)
        if result.provenance:
            prov = dict(run.provenance or {})
            prov.update(result.provenance)
            run.provenance = prov
        # A handler can persist a partial result while keeping an already
        # in-progress run editable.  Do not emit an invalid self-transition.
        if result.next_status != run.status:
            self.transition(run, result.next_status)
        self._emit(run, "executed", actor_id=user.id,
                   payload={"handler": definition.handler_key,
                            "next_status": result.next_status})
        self.db.flush()
        return result


# ── Typed Handlers ────────────────────────────────────────────────────────────

def _form_backed_handler(form_key: str) -> TaskHandler:
    """表單型任務：建立 FormInstance；必填齊全則送審，否則保留草稿。"""

    def _handler(ctx: TaskRunContext) -> TaskResult:
        import uuid as _uuid

        from app.services.fixed_form import get_form_registry
        from app.services.mka_persistence import MKARepository

        repo = MKARepository(ctx.db)
        instance = repo.create_form_instance(
            tenant_id=ctx.user.tenant_id,
            owner_id=ctx.user.id,
            form_key=form_key,
            values=ctx.inputs.get("values") or {},
            provenance={
                "task_run_id": str(ctx.run.id),
                "sources": ctx.inputs.get("sources") or {},
            },
            module_key=ctx.definition.module_key,
            scene_context=ctx.job_ctx.scene or {},
        )
        sources = {
            field: {"source": meta.get("source", "user"), "ref": meta.get("ref"),
                    "confidence": meta.get("confidence")}
            for field, meta in (ctx.inputs.get("sources") or {}).items()
            if isinstance(meta, dict)
        }
        schema = get_form_registry().get(form_key)
        final_values = dict(instance.values_json or {})
        missing = [
            f.name
            for f in (schema.fields if schema else [])
            if f.required and final_values.get(f.name) in (None, "")
        ]
        approval_id = None
        form_status = instance.status
        if not missing:
            instance, approval = repo.submit_form(
                tenant_id=ctx.user.tenant_id,
                instance_id=instance.id,
                submitted_by=ctx.user.id,
                expected_version=instance.record_version,
                idempotency_key=f"task-run-{ctx.run.id}-{_uuid.uuid4().hex[:8]}",
            )
            approval_id = str(approval.id)
            form_status = instance.status
        return TaskResult(
            output_refs={
                "form_instance_id": str(instance.id),
                "form_key": form_key,
                "form_status": form_status,
                **({"approval_id": approval_id} if approval_id else {}),
            },
            field_sources=sources,
            provenance={
                "handler": form_key,
                "form_instance_id": str(instance.id),
                "missing_fields": missing,
                **({"approval_id": approval_id} if approval_id else {}),
            },
            next_status="waiting_review" if approval_id else "in_progress",
        )

    return _handler

def _lookup_knowledge_price(
    db: Session, tenant_id: UUID, part_number: str
) -> Optional[Dict[str, Any]]:
    """知識補值工具：從租戶文件 chunks 找料號的單價。

    回傳 {value, ref, confidence}；找不到回 None（誠實缺值，不編造）。
    """
    import re

    from app.models.document import DocumentChunk

    rows = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.text.contains(part_number),
        )
        .limit(5)
        .all()
    )
    price_re = re.compile(
        re.escape(part_number) + r"[^\d]{0,20}?(?:單價|價格|price)[^\d]{0,10}([0-9,]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    )
    generic_re = re.compile(r"(?:單價|價格)\s*[：:為是]?\s*([0-9,]+(?:\.[0-9]+)?)")
    for chunk in rows:
        content = chunk.text or ""
        m = price_re.search(content)
        if not m:
            m = generic_re.search(content)
        if m:
            try:
                value = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            return {
                "value": value,
                "ref": f"doc:{chunk.document_id}",
                "confidence": 0.7,
            }
    return None


def _quote_handler(ctx: TaskRunContext) -> TaskResult:
    """報價垂直切片：知識補值 → 建立表單 → 規則計算 → 缺欄位清單 → waiting_review。"""
    from app.services.mka_persistence import MKARepository

    repo = MKARepository(ctx.db)
    values = dict(ctx.inputs.get("values") or {})
    # parse-text／語音可能留下字串數字；送審前正規化，避免 validate 因型別失敗
    for key in ("quantity", "unit_price", "tax_rate"):
        if key in values and isinstance(values[key], str):
            try:
                raw = values[key].replace(",", "").strip()
                values[key] = float(raw) if "." in raw else int(raw)
            except (TypeError, ValueError):
                pass
    field_sources: Dict[str, Any] = {
        field: {"source": meta.get("source", "user"), "ref": meta.get("ref"),
                "confidence": meta.get("confidence")}
        for field, meta in (ctx.inputs.get("sources") or {}).items()
        if isinstance(meta, dict)
    }

    # 1. 知識補值：缺 unit_price 但有料號時，從知識庫查價
    if not values.get("unit_price") and values.get("part_number"):
        hit = _lookup_knowledge_price(
            ctx.db, ctx.user.tenant_id, str(values["part_number"])
        )
        if hit:
            values["unit_price"] = hit["value"]
            field_sources["unit_price"] = {
                "source": "knowledge",
                "ref": hit["ref"],
                "confidence": hit["confidence"],
            }

    # 2. 建立表單草稿
    instance = repo.create_form_instance(
        tenant_id=ctx.user.tenant_id,
        owner_id=ctx.user.id,
        form_key="quote",
        values=values,
        provenance={
            "task_run_id": str(ctx.run.id),
            "sources": ctx.inputs.get("sources") or {},
        },
        module_key=ctx.definition.module_key,
        scene_context=ctx.job_ctx.scene or {},
    )

    # 3. 規則計算（subtotal/tax/total），來源標記 deterministic_rule
    instance = repo.calculate_form(
        tenant_id=ctx.user.tenant_id,
        instance_id=instance.id,
        actor_id=ctx.user.id,
        actor_roles=[ctx.user.role],
        is_superuser=bool(getattr(ctx.user, "is_superuser", False)),
        expected_version=instance.record_version,
    )
    calculated = (instance.calculation_snapshot or {}).get("calculated") or {}
    for field_name in calculated:
        field_sources[field_name] = {
            "source": "rule",
            "ref": f"formula:{field_name}",
            "confidence": 1.0,
        }

    # 4. 缺欄位清單（依表單 schema 的 required）
    from app.services.fixed_form import get_form_registry

    schema = get_form_registry().get("quote")
    final_values = dict(instance.values_json or {})
    missing = [
        f.name
        for f in (schema.fields if schema else [])
        if f.required and final_values.get(f.name) in (None, "")
    ]

    approval_id = None
    form_status = instance.status
    # 必填齊全才真正送審（產生 ApprovalRequest）；否則保留草稿讓使用者補欄位
    if not missing:
        import uuid as _uuid

        instance, approval = repo.submit_form(
            tenant_id=ctx.user.tenant_id,
            instance_id=instance.id,
            submitted_by=ctx.user.id,
            expected_version=instance.record_version,
            idempotency_key=f"task-run-{ctx.run.id}-{_uuid.uuid4().hex[:8]}",
        )
        approval_id = str(approval.id)
        form_status = instance.status

    return TaskResult(
        output_refs={
            "form_instance_id": str(instance.id),
            "form_key": "quote",
            "form_status": form_status,
            **({"approval_id": approval_id} if approval_id else {}),
        },
        field_sources=field_sources,
        provenance={
            "handler": "quote",
            "form_instance_id": str(instance.id),
            "calculation_snapshot": instance.calculation_snapshot or {},
            "missing_fields": missing,
            **({"approval_id": approval_id} if approval_id else {}),
        },
        next_status="waiting_review" if approval_id else "in_progress",
    )


def _interview_handler(ctx: TaskRunContext) -> TaskResult:
    """師傅訪談：建立 knowhow 草稿卡。"""
    from app.services.mka_persistence import MKARepository

    repo = MKARepository(ctx.db)
    import uuid as _uuid

    values = dict(ctx.inputs.get("values") or {})
    title = values.get("title") or ctx.inputs.get("title") or "未命名訪談"
    summary = values.get("summary") or ctx.inputs.get("summary") or ""
    raw_steps = values.get("steps") if "steps" in values else ctx.inputs.get("steps")
    if isinstance(raw_steps, str):
        steps = [line.strip() for line in raw_steps.splitlines() if line.strip()]
    else:
        steps = list(raw_steps or [])

    card = repo.create_knowhow(
        tenant_id=ctx.user.tenant_id,
        title=str(title),
        summary=str(summary),
        steps=steps,
        data={"source": "interview", "task_run_id": str(ctx.run.id)},
        owner_id=ctx.user.id,
    )
    card, approval = repo.submit_knowhow(
        tenant_id=ctx.user.tenant_id,
        knowhow_id=card.id,
        submitted_by=ctx.user.id,
        expected_version=card.version,
        idempotency_key=f"task-run-{ctx.run.id}-{_uuid.uuid4().hex[:8]}",
        actor_roles=[ctx.user.role],
        is_superuser=bool(getattr(ctx.user, "is_superuser", False)),
    )
    return TaskResult(
        output_refs={
            "knowhow_card_id": str(card.id),
            "approval_id": str(approval.id),
            "knowhow_status": card.status,
        },
        provenance={
            "handler": "interview",
            "knowhow_card_id": str(card.id),
            "approval_id": str(approval.id),
        },
        next_status="waiting_review",
    )


def _not_implemented(task_key: str) -> TaskHandler:
    def _handler(ctx: TaskRunContext) -> TaskResult:
        raise TaskHandlerNotImplemented(
            f"任務 {task_key} 的 handler 將於後續 Phase 實作"
        )

    return _handler


TASK_HANDLERS: Dict[str, TaskHandler] = {
    "quote": _quote_handler,
    "incident": _form_backed_handler("incident_report"),
    "handover": _form_backed_handler("shift_handover"),
    "quality_8d": _form_backed_handler("quality_8d"),
    "interview": _interview_handler,
    "training": _form_backed_handler("training_checklist"),
    "daily_report": _form_backed_handler("daily_report"),
    # ask 的主路徑是 /chat 問答管線；TaskRun 化屬於後續範圍，明確失敗而非假裝成功
    "ask": _not_implemented("ask"),
}


def get_task_engine(db: Session) -> TaskEngine:
    return TaskEngine(db)
