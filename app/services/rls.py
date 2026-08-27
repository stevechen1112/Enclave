"""PostgreSQL Row-Level Security 租戶隔離（ADR-012）。

設計要點（嚴謹性要求）：

1. **fail-closed**：未設定 ``app.tenant_id`` 的連線在 enforce 後查不到任何
   租戶列（policy 比對 NULL 不成立），而不是看到全部。
2. **transaction-scoped**：一律用 ``set_config(..., is_local=true)``，
   連線歸還 pool 後 context 自動消失，杜絕跨請求殘留。
3. **bypass 僅限平台維運**：``apply_rls_bypass`` 僅供獨立維運身分執行
   migration／跨租戶 retention 等作業；普通請求與登入流程不可使用。
4. **分階段**：``RLS_ENFORCEMENT_ENABLED=false``（預設）時 policy 已建立
   但表 owner 不受 FORCE 約束（shadow）；enforce 由 migration 讀同名
   環境變數決定是否 ``FORCE ROW LEVEL SECURITY``。
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TENANT_GUC = "app.tenant_id"
BYPASS_GUC = "app.bypass_rls"
BYPASS_ROLE = "enclave_rls_bypass"


def _is_postgres(db: Session) -> bool:
    try:
        return db.bind is not None and db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def apply_rls_context(db: Session, tenant_id: UUID) -> bool:
    """在目前 transaction 設定租戶 context，並關閉 bypass。

    回傳是否實際執行（非 PostgreSQL 連線——例如單元測試 mock——直接略過）。
    ``tenant_id`` 必須是 UUID 實例；字串一律拒絕，避免把未驗證輸入送進 GUC。

    context 同時記入 ``db.info``，由 ``register_session_events`` 掛上的
    ``after_begin`` 監聽器在**每次新 transaction 開始時自動重設**——
    ``set_config(..., true)`` 是 transaction-scoped，request／task 內的
    每次 commit 都會清空 GUC，沒有重設機制的話 enforce 階段會在
    第一個 commit 後 fail-closed（或更糟：寫入被 WITH CHECK 拒絕）。
    """
    if not isinstance(tenant_id, UUID):
        raise TypeError(f"tenant_id must be UUID, got {type(tenant_id).__name__}")
    if not _is_postgres(db):
        return False
    db.info[_INFO_TENANT_KEY] = str(tenant_id)
    db.info.pop(_INFO_BYPASS_KEY, None)
    register_session_events()
    _set_gucs(db, str(tenant_id), bypass=False)
    return True


def _set_gucs(db: Session, tenant_id: Optional[str], *, bypass: bool) -> None:
    """實際下 set_config（transaction-scoped）。內部使用。"""
    db.execute(
        text(f"SELECT set_config('{BYPASS_GUC}', :bv, true)"),
        {"bv": "on" if bypass else "off"},
    )
    db.execute(
        text(f"SELECT set_config('{TENANT_GUC}', :tid, true)"),
        {"tid": tenant_id or ""},
    )


# ---------------------------------------------------------------------------
# commit 後自動重設 context（code review 發現：SET LOCAL 隨 transaction 結束消失）
# ---------------------------------------------------------------------------

_INFO_TENANT_KEY = "_rls_tenant_id"
_INFO_BYPASS_KEY = "_rls_bypass"
_events_registered = False


def _after_begin(session, transaction, connection):
    """每個新 transaction 開始時，依 session.info 重設 RLS GUC。"""
    if connection.dialect.name != "postgresql":
        return
    tid = session.info.get(_INFO_TENANT_KEY)
    bypass = bool(session.info.get(_INFO_BYPASS_KEY))
    if not tid and not bypass:
        return
    connection.execute(
        text(f"SELECT set_config('{BYPASS_GUC}', :bv, true)"),
        {"bv": "on" if bypass else "off"},
    )
    connection.execute(
        text(f"SELECT set_config('{TENANT_GUC}', :tid, true)"),
        {"tid": tid or ""},
    )


def register_session_events() -> None:
    """在 SQLAlchemy Session 類別上掛 after_begin 監聽器（冪等）。"""
    global _events_registered
    if _events_registered:
        return
    from sqlalchemy import event

    event.listen(Session, "after_begin", _after_begin)
    _events_registered = True


def apply_rls_bypass(
    db: Session,
    *,
    actor_identity: str,
    operation: str,
    reason: str,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """平台維運專用：本 transaction 內跳過 RLS。

    合法用途僅限 migration／跨租戶 retention 等平台維運任務。
    登入流程改由只回傳 tenant UUID 的 SECURITY DEFINER function
    建立 context，不再使用 bypass。
    bypass 會記入 ``db.info`` 隨 commit 後的新 transaction 重設——
    這是刻意為之：平台維運任務（如 audit）跨多個 commit 仍需 bypass；
    請勿在一般請求路徑使用。
    """
    if not _is_postgres(db):
        return False
    if not actor_identity.strip() or not operation.strip() or not reason.strip():
        raise ValueError("bypass audit actor, operation, and reason are required")
    register_session_events()
    authorised = db.execute(
        text("SELECT pg_has_role(current_user, :role, 'member')"),
        {"role": BYPASS_ROLE},
    ).scalar()
    if authorised is not True:
        raise PermissionError(
            "database identity is not authorised for tenant RLS bypass"
        )
    db.execute(text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    db.execute(
        text(
            """
            INSERT INTO platform_maintenance_audit
                (actor_identity, operation, reason, correlation_id, metadata_json)
            VALUES
                (:actor_identity, :operation, :reason, :correlation_id,
                 CAST(:metadata_json AS json))
            """
        ),
        {
            "actor_identity": actor_identity,
            "operation": operation,
            "reason": reason,
            "correlation_id": correlation_id,
            "metadata_json": json.dumps(metadata or {}, sort_keys=True),
        },
    )
    db.info[_INFO_BYPASS_KEY] = True
    return True


def current_rls_context(db: Session) -> Optional[str]:
    """回傳目前 transaction 的租戶 context（未設定回 None）。"""
    if not _is_postgres(db):
        return None
    return db.execute(text(f"SELECT current_setting('{TENANT_GUC}', true)")).scalar()


def resolve_login_tenant(db: Session, email: str) -> UUID | None:
    """Resolve only the tenant UUID needed to establish pre-login RLS context.

    PostgreSQL grants the fixed SECURITY DEFINER function only to the
    ``enclave_application`` marker role.  It never returns password hashes or a
    cross-tenant user row.  Non-PostgreSQL unit tests deliberately return no
    result; callers fail authentication closed.
    """
    if not _is_postgres(db) or not email.strip():
        return None
    normalised_email = email.strip().lower()
    resolver_exists = db.execute(
        text("SELECT to_regprocedure('public.enclave_resolve_login_tenant(text)')")
    ).scalar()
    if resolver_exists:
        value = db.execute(
            text("SELECT public.enclave_resolve_login_tenant(:email)"),
            {"email": normalised_email},
        ).scalar()
    else:
        # Base.metadata-only test databases do not contain migration functions.
        # Permit the narrow fallback only for a PostgreSQL superuser; ordinary
        # application roles fail closed and must use the audited migration DDL.
        is_superuser = db.execute(
            text(
                "SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user"
            )
        ).scalar()
        if is_superuser is not True:
            raise RuntimeError("secure login tenant resolver is not installed")
        value = db.execute(
            text(
                "SELECT tenant_id FROM public.users WHERE lower(email) = :email LIMIT 1"
            ),
            {"email": normalised_email},
        ).scalar()
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


@contextmanager
def task_session(session_factory, tenant_id: UUID) -> Iterator[Session]:
    """Celery task 專用：開 session 並立即設定租戶 context（ADR-012 措施 6）。

    用法::

        with task_session(SessionLocal, UUID(tenant_id)) as db:
            ...

    enforce 階段未經此 helper 的 task session 將查無租戶列（fail-closed）。
    """
    db = session_factory()
    try:
        apply_rls_context(db, tenant_id)
        yield db
    finally:
        db.close()


def audit_tenant_visibility(db: Session) -> List[Dict[str, Any]]:
    """shadow 稽核報告：逐表列出「目前 context 可見列數 vs 總列數」。

    用法：在已 ``apply_rls_context(tenant)`` 的 session 上執行。
    - ``visible < total``：policy 生效，有他租戶列被擋（預期）
    - ``visible == total`` 且多租戶共存：異常，表示 context 未生效或資料全屬同租戶
    僅供 shadow 階段巡檢與 CG-RLS 閘門報告使用，非請求路徑。
    """
    if not _is_postgres(db):
        return []
    tables = db.execute(
        text(
            """
            SELECT c.table_name
            FROM information_schema.columns c
            JOIN pg_catalog.pg_class pc
              ON pc.relname = c.table_name
            JOIN pg_catalog.pg_namespace pn
              ON pn.oid = pc.relnamespace AND pn.nspname = 'public'
            WHERE c.table_schema = 'public'
              AND c.column_name = 'tenant_id'
              AND c.is_nullable = 'NO'
              AND c.table_name <> 'tenants'
              AND pc.relrowsecurity = true
            ORDER BY c.table_name
            """
        )
    ).fetchall()

    # 先記住呼叫方 context；total 用 bypass 統計（enforce 下 RLS 也會過濾 count）。
    # 無論先前有無 context，結束前都必須關閉 bypass——否則同一 transaction
    # 後續查詢會跨租戶讀取（code review 發現的洩漏路徑）。
    prior = current_rls_context(db)
    apply_rls_bypass(
        db,
        actor_identity="tenant-visibility-audit",
        operation="audit_tenant_visibility",
        reason="Compare RLS-visible rows with maintenance totals",
    )
    try:
        totals = {
            table: db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()  # noqa: S608
            for (table,) in tables
        }
    finally:
        if prior:
            _set_gucs(db, prior, bypass=False)
            db.info[_INFO_TENANT_KEY] = prior
            db.info.pop(_INFO_BYPASS_KEY, None)
        else:
            _set_gucs(db, None, bypass=False)
            db.info.pop(_INFO_TENANT_KEY, None)
            db.info.pop(_INFO_BYPASS_KEY, None)

    report: List[Dict[str, Any]] = []
    for (table,) in tables:
        # 表名來自 information_schema 且經 relrowsecurity 過濾，非使用者輸入
        visible = db.execute(
            text(
                f'SELECT count(*) FROM "{table}" '  # noqa: S608
                f"WHERE tenant_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid"
            )
        ).scalar()
        report.append(
            {"table": table, "total": totals[table], "visible_in_context": visible}
        )
    return report
