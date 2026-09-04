"""Deterministic, synthetic-only public Demo tenant lifecycle.

The seeder never copies an existing tenant or document.  Reset is transactional
and only accepts a row explicitly marked ``is_demo`` whose name states that it
is not a real company.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.base_class import Base
from app.demo.manifest import (
    DEMO_PERSONAS,
    DEMO_TENANT_ID,
    DEMO_TENANT_NAME,
)

SYNTHETIC_DOCUMENTS: tuple[dict[str, str], ...] = (
    {
        "key": "company_handbook",
        "filename": "DEMO_合成工廠_公司與安全手冊.md",
        "genre": "policy",
        "content": """[合成展示資料｜非真實公司]
Enclave 合成展示工廠位於示範園區 A 棟，所有人名、設備、客戶與金額皆為虛構。
進入產線必須配戴安全帽、護目鏡與安全鞋。設備異常時先按急停、掛上停機牌，
再通知設備課；未完成斷電與殘壓確認不得拆護罩。""",
    },
    {
        "key": "p100_price",
        "filename": "DEMO_P-100_虛構報價與交期規則.md",
        "genre": "quote",
        "content": """[合成展示資料｜非真實客戶與價格]
料號 P-100 為虛構精機配件。標準單價每件新台幣 120 元，最低訂購量 100 件，
標準交期 14 個工作天。數量達 500 件時示範折扣為 5%，報價有效期限 30 天，
付款條件為月結 30 天，營業稅 5%。""",
    },
    {
        "key": "eq100_sop",
        "filename": "DEMO_EQ-100_虛構設備換線SOP.md",
        "genre": "manual",
        "content": """[合成展示資料｜非真實設備]
EQ-100 張力控制機換線步驟：一、按停止並執行斷電上鎖；二、確認壓力表歸零；
三、以 8 N·m 鎖付導輪固定螺栓；四、手動盤車兩圈確認無干涉；五、低速試車三分鐘。
若顯示 E-07，先檢查張力感測器接頭，再量測訊號線；不得直接短接安全迴路。""",
    },
    {
        "key": "quality_8d",
        "filename": "DEMO_虛構客訴_8D處理範例.md",
        "genre": "report",
        "content": """[合成展示資料｜非真實客訴]
虛構客戶東方機械反映 P-100 外徑超差。圍堵措施為隔離批號 DEMO-2408 並全檢；
根因示範為量具未依班次執行歸零確認。矯正措施：更新首件檢查表、每班點檢量具、
七日後抽查 30 件。8D 報告須由品保主管核准後結案。""",
    },
    {
        "key": "master_knowhow",
        "filename": "DEMO_老師傅經驗_張力飄移判斷.md",
        "genre": "sop",
        "content": """[合成展示資料｜非真實師傅訪談]
張力數值緩慢飄高時，先比較空車與帶料狀態；空車也飄移，多半先查感測器零點與接頭。
只有帶料才飄移，依序檢查材料批次、導輪髒污與煞車器溫升。每次只改一個條件並記錄，
禁止用提高張力上限掩蓋問題。此經驗卡仍須與正式 SOP 一起使用。""",
    },
)


def _stable_id(tenant_id: UUID, *parts: str) -> UUID:
    return uuid5(tenant_id, ":".join(parts))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _upsert_demo_documents(
    db: Session, tenant_id: UUID, owner_id: UUID
) -> dict[str, int]:
    from app.models.asset import AssetRevision, SourceAsset
    from app.models.document import Document, DocumentChunk
    from app.models.ingestion import IngestionJob
    from app.models.kb_maintenance import DocumentVersion
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
    from app.models.knowledge_engine import (
        DocumentProfile,
        KnowledgeBaseRevisionDocument,
    )

    kb_id = _stable_id(tenant_id, "knowledge-base")
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb is None:
        kb = KnowledgeBase(id=kb_id, tenant_id=tenant_id)
        db.add(kb)
    kb.name = "合成展示知識庫"
    kb.description = "僅含 Enclave 自行產生的虛構製造業資料"
    kb.status = "active"
    kb.active_revision = 1
    db.flush()

    revision_id = _stable_id(tenant_id, "knowledge-base", "revision", "1")
    revision = (
        db.query(KnowledgeBaseRevision)
        .filter(KnowledgeBaseRevision.id == revision_id)
        .first()
    )
    if revision is None:
        revision = KnowledgeBaseRevision(
            id=revision_id,
            kb_id=kb.id,
            revision=1,
        )
        db.add(revision)

    hashes: list[str] = []
    for doc_index, spec in enumerate(SYNTHETIC_DOCUMENTS):
        text = spec["content"].strip()
        digest = _content_hash(text)
        hashes.append(digest)
        document_id = _stable_id(tenant_id, "document", spec["key"])
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is None:
            document = Document(id=document_id, tenant_id=tenant_id)
            db.add(document)
        document.knowledge_base_id = kb.id
        document.filename = spec["filename"]
        document.file_type = "md"
        document.file_path = f"demo://synthetic/{spec['key']}.md"
        document.file_size = len(text.encode("utf-8"))
        document.source_type = "synthetic_demo"
        document.source_system = None
        document.source_record_id = None
        document.external_version = "synthetic-v1"
        document.genre = spec["genre"]
        document.content_hash = digest
        document.version = 1
        document.status = "completed"
        document.chunk_count = 1
        document.error_message = None
        document.quality_report = {
            "synthetic": True,
            "label": "合成展示資料",
            "quality_score": 1.0,
        }
        document.tombstoned_at = None
        document.uploaded_by = owner_id
        document.department_id = None
        db.flush()

        # The public Demo must exercise the canonical asset platform used by
        # the product UI, not only the retained legacy Document projection.
        asset_id = _stable_id(tenant_id, "source-asset", spec["key"])
        asset = db.query(SourceAsset).filter(SourceAsset.id == asset_id).first()
        if asset is None:
            asset = SourceAsset(id=asset_id, tenant_id=tenant_id)
            db.add(asset)
        asset.asset_kind = "document"
        asset.title = spec["filename"]
        asset.source_system = "upload"
        asset.source_record_id = None
        asset.data_classification = "internal"
        asset.acl_reference = {
            "visibility": "tenant",
            "policy_revision": 1,
            "schema_version": "1.0",
        }
        asset.metadata_json = {
            "synthetic_demo": True,
            "direct_intake": True,
            "legacy_document_id": str(document.id),
        }
        asset.current_revision = 1
        asset.status = "ready"
        asset.created_by = owner_id
        asset.captured_by = owner_id
        asset.tombstoned_at = None
        db.flush()

        asset_revision_id = _stable_id(tenant_id, "asset-revision", spec["key"], "1")
        asset_revision = (
            db.query(AssetRevision)
            .filter(AssetRevision.id == asset_revision_id)
            .first()
        )
        if asset_revision is None:
            asset_revision = AssetRevision(
                id=asset_revision_id,
                tenant_id=tenant_id,
                asset_id=asset.id,
                revision=1,
            )
            db.add(asset_revision)
        asset_revision.media_type = "text/markdown"
        asset_revision.content_uri = document.file_path
        asset_revision.content_hash = digest
        asset_revision.external_version = "synthetic-v1"
        asset_revision.byte_size = document.file_size
        asset_revision.ingestion_status = "ready"
        asset_revision.retention_policy = {"class": "synthetic_demo"}
        asset_revision.metadata_json = {
            "synthetic_demo": True,
            "legacy_document_id": str(document.id),
        }
        asset_revision.created_by = owner_id
        db.flush()

        ingestion_job_id = _stable_id(tenant_id, "ingestion-job", spec["key"], "1")
        ingestion_job = (
            db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        )
        if ingestion_job is None:
            ingestion_job = IngestionJob(
                id=ingestion_job_id,
                tenant_id=tenant_id,
                asset_revision_id=asset_revision.id,
            )
            db.add(ingestion_job)
        ingestion_job.adapter_key = "synthetic_demo"
        ingestion_job.adapter_version = "1.0"
        ingestion_job.requested_capabilities = ["retrieval", "citation"]
        ingestion_job.idempotency_key = f"synthetic-demo:{spec['key']}:v1"
        ingestion_job.status = "ready"
        ingestion_job.phase = "completed"
        ingestion_job.attempt = 1
        ingestion_job.quality_state = "ready"
        ingestion_job.readiness = {
            "answer_ready": True,
            "citation_ready": True,
            "synthetic_demo": True,
        }
        ingestion_job.error = {}
        ingestion_job.completed_at = datetime.now(UTC)
        db.flush()

        version_id = _stable_id(tenant_id, "document-version", spec["key"], "1")
        version = (
            db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        )
        if version is None:
            version = DocumentVersion(
                id=version_id,
                tenant_id=tenant_id,
                document_id=document.id,
                version=1,
            )
            db.add(version)
        version.filename = document.filename
        version.file_path = document.file_path
        version.file_size = document.file_size
        version.file_type = document.file_type
        version.chunk_count = 1
        version.status = "completed"
        version.quality_report = document.quality_report
        version.uploaded_by = owner_id
        version.change_note = "Deterministic synthetic Demo seed"
        version.content_snapshot = text
        db.flush()

        chunk_id = _stable_id(tenant_id, "chunk", spec["key"], "0")
        chunk = db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).first()
        if chunk is None:
            chunk = DocumentChunk(
                id=chunk_id,
                tenant_id=tenant_id,
                document_id=document.id,
                document_revision=1,
                chunk_index=0,
            )
            db.add(chunk)
        embedding = [0.001] * 1024
        embedding[doc_index] = 1.0
        chunk.text = text
        chunk.chunk_hash = digest
        chunk.embedding = embedding
        chunk.metadata_json = {
            "filename": document.filename,
            "section": "合成展示資料",
            "synthetic_demo": True,
        }

        profile_id = _stable_id(tenant_id, "document-profile", spec["key"], "1")
        profile = (
            db.query(DocumentProfile).filter(DocumentProfile.id == profile_id).first()
        )
        if profile is None:
            profile = DocumentProfile(
                id=profile_id,
                tenant_id=tenant_id,
                document_id=document.id,
                document_revision=1,
                format_family="markdown",
                support_level="full",
                profiler_version="demo-synthetic-v1",
                content_hash=digest,
            )
            db.add(profile)
        profile.language_profile = {"primary": "zh-TW"}
        profile.page_count = 1
        profile.structure_map = {"sections": ["合成展示資料"]}
        profile.capability_readiness = {
            "retrieval": True,
            "citation": True,
            "synthetic": True,
        }
        profile.warnings = ["synthetic_demo_content"]
        profile.quality_score = 1.0
        profile.answer_ready = True

        membership_id = _stable_id(tenant_id, "membership", spec["key"], "1")
        membership = (
            db.query(KnowledgeBaseRevisionDocument)
            .filter(KnowledgeBaseRevisionDocument.id == membership_id)
            .first()
        )
        if membership is None:
            membership = KnowledgeBaseRevisionDocument(
                id=membership_id,
                tenant_id=tenant_id,
                kb_revision_id=revision.id,
                document_id=document.id,
                document_version_id=version.id,
                document_revision=1,
                content_hash=digest,
            )
            db.add(membership)
        membership.acl_snapshot = {"visibility": "tenant", "synthetic_demo": True}
        membership.policy_revision = 1

    manifest_hash = _content_hash("\n".join(sorted(hashes)))
    revision.status = "active"
    revision.manifest_hash = manifest_hash
    revision.policy_revision = 1
    revision.change_summary = "Deterministic synthetic Demo corpus"
    revision.manifest_json = {
        "synthetic_demo": True,
        "document_count": len(SYNTHETIC_DOCUMENTS),
        "content_hashes": sorted(hashes),
    }
    revision.index_namespace = f"demo-{tenant_id}-r1"
    revision.activated_at = datetime.now(UTC)
    db.flush()
    return {"documents": len(SYNTHETIC_DOCUMENTS), "chunks": len(SYNTHETIC_DOCUMENTS)}


def seed_demo_tenant(db: Session) -> dict[str, Any]:
    """Create/update the canonical isolated Demo tenant without committing."""
    import app.models  # noqa: F401
    from app.models.mka import (
        JobRole,
        KnowhowCardModel,
        SceneRegistry,
        TenantModuleBinding,
        UserJobRoleAssignment,
    )
    from app.models.permission import Department
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.mka_module_seed import (
        CANONICAL_MODULES,
        ensure_tenant_module_bindings,
        seed_canonical_modules,
        seed_canonical_task_definitions,
        seed_default_job_roles,
    )
    from app.services.workflow_repository import WorkflowRepository

    tenant = db.query(Tenant).filter(Tenant.id == DEMO_TENANT_ID).first()
    if tenant is not None and not tenant.is_demo:
        raise RuntimeError("canonical Demo tenant UUID belongs to a non-Demo tenant")
    if tenant is None:
        tenant = Tenant(id=DEMO_TENANT_ID)
        db.add(tenant)
    tenant.name = DEMO_TENANT_NAME
    tenant.plan = "enterprise"
    tenant.status = "active"
    tenant.is_demo = True
    tenant.max_users = 12
    tenant.max_documents = 50
    tenant.max_storage_mb = 512
    tenant.monthly_query_limit = 10_000
    tenant.require_mfa = False
    db.flush()

    from app.services.sidecar_binding import ensure_binding

    sidecar_binding = ensure_binding(db, tenant.id)
    sidecar_binding.ragflow_dataset_id = None
    sidecar_binding.weknora_kb_id = None
    sidecar_binding.pipeshub_org_id = None
    sidecar_binding.credentials_ref = None

    departments: dict[str, Department] = {}
    for name in sorted({str(spec["department"]) for spec in DEMO_PERSONAS.values()}):
        department_id = _stable_id(tenant.id, "department", name)
        department = db.query(Department).filter(Department.id == department_id).first()
        if department is None:
            department = Department(id=department_id, tenant_id=tenant.id)
            db.add(department)
        department.name = name
        department.description = "合成展示組織，不代表任何真實公司"
        department.is_active = True
        departments[name] = department
    db.flush()

    users: dict[str, User] = {}
    for persona, spec in DEMO_PERSONAS.items():
        email = str(spec["email"])
        user = db.query(User).filter(User.email == email).first()
        if user is not None and user.tenant_id != tenant.id:
            raise RuntimeError(
                f"Demo email is already owned by another tenant: {email}"
            )
        if user is None:
            user = User(
                id=_stable_id(tenant.id, "user", persona),
                email=email,
                hashed_password="pending-demo-password-rotation",
                tenant_id=tenant.id,
            )
            db.add(user)
        # Passwordless doors are the only supported entry. Rotate to an unknown
        # high-entropy value on every seed so legacy shared Demo passwords die.
        user.hashed_password = get_password_hash(secrets.token_urlsafe(48))
        user.full_name = str(spec["full_name"])
        user.role = str(spec["security_role"])
        user.status = "active"
        user.email_verified = True
        user.is_superuser = False
        user.mfa_enabled = False
        user.mfa_secret = None
        user.department_id = departments[str(spec["department"])].id
        users[persona] = user
    db.flush()

    seed_canonical_modules(db)
    seed_canonical_task_definitions(db)
    seed_default_job_roles(db, tenant.id)
    canonical_module_keys = tuple(str(spec["module_key"]) for spec in CANONICAL_MODULES)
    # The public Demo is a deterministic synthetic fixture, not a customer
    # workspace. Remove bindings for modules retired from the canonical Demo
    # catalog so an ordinary deploy remains idempotent across catalog changes.
    db.query(TenantModuleBinding).filter(
        TenantModuleBinding.tenant_id == tenant.id,
        TenantModuleBinding.module_key.notin_(canonical_module_keys),
    ).delete(synchronize_session=False)
    ensure_tenant_module_bindings(db, tenant.id)
    roles = {
        role.role_key: role
        for role in db.query(JobRole).filter(JobRole.tenant_id == tenant.id).all()
    }
    for persona, spec in DEMO_PERSONAS.items():
        role_key = spec.get("job_role")
        user = users[persona]
        if not role_key:
            user.active_job_role_id = None
            continue
        role = roles[str(role_key)]
        assignment = (
            db.query(UserJobRoleAssignment)
            .filter(
                UserJobRoleAssignment.tenant_id == tenant.id,
                UserJobRoleAssignment.user_id == user.id,
                UserJobRoleAssignment.job_role_id == role.id,
            )
            .first()
        )
        if assignment is None:
            assignment = UserJobRoleAssignment(
                id=_stable_id(tenant.id, "job-role-assignment", persona),
                tenant_id=tenant.id,
                user_id=user.id,
                job_role_id=role.id,
            )
            db.add(assignment)
        assignment.department_id = user.department_id
        assignment.is_primary = True
        assignment.active = True
        user.active_job_role_id = role.id
    db.flush()

    WorkflowRepository(db).ensure_form_definitions(tenant_id=tenant.id)

    scene_id = _stable_id(tenant.id, "scene", "eq100")
    scene = db.query(SceneRegistry).filter(SceneRegistry.id == scene_id).first()
    if scene is None:
        scene = SceneRegistry(id=scene_id, tenant_id=tenant.id, token="DEMO-EQ100")
        db.add(scene)
    scene.site_id = "DEMO-SITE"
    scene.plant_id = "DEMO-PLANT-A"
    scene.line_id = "DEMO-LINE-1"
    scene.equipment_id = "EQ-100-01"
    scene.equipment_model = "EQ-100"
    scene.label = "合成展示設備 EQ-100（非真實設備）"
    scene.active = True

    card_id = _stable_id(tenant.id, "knowhow", "tension-drift")
    card = db.query(KnowhowCardModel).filter(KnowhowCardModel.id == card_id).first()
    if card is None:
        card = KnowhowCardModel(
            id=card_id,
            tenant_id=tenant.id,
            card_id="DEMO-KH-001",
        )
        db.add(card)
    card.owner_id = users["master"].id
    card.title = "[合成展示] 張力飄移的逐項判斷"
    card.summary = "先分辨空車或帶料才飄移，每次只改一個條件。"
    card.status = "approved"
    card.authority_level = 60
    card.risk_level = "medium"
    card.applicable_roles = ["master", "equipment", "newcomer"]
    card.equipment_ids = ["EQ-100-01"]
    card.steps = [
        "比較空車與帶料狀態",
        "檢查感測器零點與接頭",
        "檢查導輪髒污與煞車器溫升",
        "一次只調整一項並記錄",
    ]
    card.cautions = ["不得短接安全迴路", "須與正式 SOP 一起使用"]
    card.source_type = "synthetic_demo"
    card.interviewee = "虛構師傅 林火旺"
    card.interviewer = "Enclave 合成資料產生器"
    card.version = 1
    card.effective_from = datetime.now(UTC)
    card.review_due_at = datetime.now(UTC) + timedelta(days=90)
    db.flush()

    document_counts = _upsert_demo_documents(db, tenant.id, users["admin"].id)
    db.flush()
    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "personas": len(users),
        **document_counts,
    }


def _tenant_scope(table, tenant_id: UUID, memo, stack):
    if table in memo:
        return memo[table]
    if table in stack:
        return None
    if table.name == "tenants":
        result = table.c.id == tenant_id
        memo[table] = result
        return result
    if "tenant_id" in table.c:
        result = table.c.tenant_id == tenant_id
        memo[table] = result
        return result

    clauses = []
    next_stack = set(stack)
    next_stack.add(table)
    for foreign_key in table.foreign_keys:
        parent = foreign_key.column.table
        parent_scope = _tenant_scope(parent, tenant_id, memo, next_stack)
        if parent_scope is not None:
            clauses.append(
                foreign_key.parent.in_(select(foreign_key.column).where(parent_scope))
            )
    result = or_(*clauses) if clauses else None
    memo[table] = result
    return result


def purge_demo_tenant(db: Session, tenant_id: UUID = DEMO_TENANT_ID) -> dict[str, int]:
    """Transactionally purge one explicitly synthetic Demo tenant."""
    import app.models  # noqa: F401
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return {}
    if not tenant.is_demo or "非真實公司" not in tenant.name:
        raise RuntimeError(
            "refusing to purge a tenant not explicitly marked synthetic Demo"
        )

    memo = {}
    deleted: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "alembic_version":
            continue
        scope = _tenant_scope(table, tenant_id, memo, set())
        if scope is None:
            continue
        result = db.execute(delete(table).where(scope))
        if result.rowcount:
            deleted[table.name] = int(result.rowcount)
    db.flush()
    db.expire_all()
    return deleted


def reset_demo_tenant(db: Session) -> dict[str, Any]:
    """Purge and recreate the canonical Demo in the caller's transaction."""
    deleted = purge_demo_tenant(db, DEMO_TENANT_ID)
    seeded = seed_demo_tenant(db)
    seeded["deleted_rows"] = sum(deleted.values())
    return seeded


def verify_demo_tenant(db: Session) -> dict[str, Any]:
    """Return evidence that the public Demo contains only the expected corpus."""
    import app.models  # noqa: F401
    from app.models.asset import AssetRevision, SourceAsset
    from app.models.connector import ConnectorInstance
    from app.models.document import Document
    from app.models.ingestion import IngestionJob
    from app.models.kb_maintenance import DocumentVersion
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
    from app.models.mka import (
        FormDefinition,
        JobRole,
        KnowhowCardModel,
        SceneRegistry,
        TenantModuleBinding,
        UserJobRoleAssignment,
    )
    from app.models.sidecar_binding import TenantSidecarBinding
    from app.models.tenant import Tenant, TenantSSOConfig
    from app.models.user import User
    from app.services.document_readiness import load_document_answer_states
    from app.services.fixed_form import get_form_registry
    from app.services.mka_module_seed import CANONICAL_MODULES, DEFAULT_JOB_ROLES

    tenant = db.query(Tenant).filter(Tenant.id == DEMO_TENANT_ID).first()
    users = db.query(User).filter(User.tenant_id == DEMO_TENANT_ID).all()
    documents = db.query(Document).filter(Document.tenant_id == DEMO_TENANT_ID).all()
    source_assets = (
        db.query(SourceAsset).filter(SourceAsset.tenant_id == DEMO_TENANT_ID).all()
    )
    asset_revisions = (
        db.query(AssetRevision).filter(AssetRevision.tenant_id == DEMO_TENANT_ID).all()
    )
    ingestion_jobs = (
        db.query(IngestionJob).filter(IngestionJob.tenant_id == DEMO_TENANT_ID).all()
    )
    answer_states = load_document_answer_states(
        db,
        tenant_id=DEMO_TENANT_ID,
        documents=documents,
    )
    expected_hashes = {
        _content_hash(spec["content"].strip()) for spec in SYNTHETIC_DOCUMENTS
    }
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.tenant_id == DEMO_TENANT_ID)
        .all()
    )
    active_revisions = (
        db.query(KnowledgeBaseRevision)
        .join(KnowledgeBase)
        .filter(
            KnowledgeBase.tenant_id == DEMO_TENANT_ID,
            KnowledgeBase.status == "active",
            KnowledgeBaseRevision.status == "active",
            KnowledgeBaseRevision.revision == KnowledgeBase.active_revision,
        )
        .count()
    )
    knowledge_bases = (
        db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == DEMO_TENANT_ID).all()
    )
    job_roles = db.query(JobRole).filter(JobRole.tenant_id == DEMO_TENANT_ID).all()
    module_bindings = (
        db.query(TenantModuleBinding)
        .filter(TenantModuleBinding.tenant_id == DEMO_TENANT_ID)
        .all()
    )
    form_definitions = (
        db.query(FormDefinition)
        .filter(FormDefinition.tenant_id == DEMO_TENANT_ID)
        .all()
    )
    scenes = (
        db.query(SceneRegistry).filter(SceneRegistry.tenant_id == DEMO_TENANT_ID).all()
    )
    knowhow_cards = (
        db.query(KnowhowCardModel)
        .filter(KnowhowCardModel.tenant_id == DEMO_TENANT_ID)
        .all()
    )
    sidecar_bindings = (
        db.query(TenantSidecarBinding)
        .filter(TenantSidecarBinding.tenant_id == DEMO_TENANT_ID)
        .all()
    )
    checks = {
        "tenant_marked_demo": bool(tenant and tenant.is_demo),
        "synthetic_tenant_name": bool(tenant and "非真實公司" in tenant.name),
        "exact_personas": {user.email for user in users}
        == {str(spec["email"]) for spec in DEMO_PERSONAS.values()},
        "no_platform_superuser": all(not user.is_superuser for user in users),
        "synthetic_documents_only": len(documents) == len(SYNTHETIC_DOCUMENTS)
        and all(
            document.source_type == "synthetic_demo"
            and str(document.file_path or "").startswith("demo://synthetic/")
            and document.source_system is None
            for document in documents
        )
        and {document.content_hash for document in documents} == expected_hashes,
        "synthetic_versions_only": len(versions) == len(SYNTHETIC_DOCUMENTS)
        and all(
            str(version.file_path or "").startswith("demo://synthetic/")
            and str(version.content_snapshot or "").startswith("[合成展示資料")
            for version in versions
        ),
        "canonical_assets_only": len(source_assets) == len(SYNTHETIC_DOCUMENTS)
        and len(asset_revisions) == len(SYNTHETIC_DOCUMENTS)
        and all(
            asset.asset_kind == "document"
            and asset.source_system == "upload"
            and asset.status == "ready"
            and asset.current_revision == 1
            and bool((asset.metadata_json or {}).get("synthetic_demo"))
            for asset in source_assets
        )
        and {revision.content_hash for revision in asset_revisions} == expected_hashes
        and all(revision.ingestion_status == "ready" for revision in asset_revisions)
        and len(ingestion_jobs) == len(SYNTHETIC_DOCUMENTS)
        and all(
            job.status == "ready"
            and job.quality_state == "ready"
            and bool((job.readiness or {}).get("answer_ready"))
            for job in ingestion_jobs
        ),
        "all_documents_answer_ready": len(answer_states) == len(documents)
        and all(state.answer_ready for state in answer_states.values()),
        "one_exact_knowledge_base": len(knowledge_bases) == 1
        and knowledge_bases[0].name == "合成展示知識庫"
        and active_revisions == 1,
        "exact_job_roles": {role.role_key for role in job_roles}
        == {str(spec["role_key"]) for spec in DEFAULT_JOB_ROLES}
        and all(role.active for role in job_roles),
        "persona_assignments_present": db.query(UserJobRoleAssignment)
        .filter(
            UserJobRoleAssignment.tenant_id == DEMO_TENANT_ID,
            UserJobRoleAssignment.active.is_(True),
        )
        .count()
        == 5,
        "exact_module_bindings": {binding.module_key for binding in module_bindings}
        == {str(spec["module_key"]) for spec in CANONICAL_MODULES}
        and all(binding.enabled for binding in module_bindings),
        "exact_form_definitions": {
            definition.form_key for definition in form_definitions
        }
        == set(get_form_registry().list_forms())
        and all(definition.status == "active" for definition in form_definitions),
        "exact_scene": len(scenes) == 1
        and scenes[0].token == "DEMO-EQ100"
        and scenes[0].active,
        "exact_knowhow_card": len(knowhow_cards) == 1
        and knowhow_cards[0].card_id == "DEMO-KH-001"
        and knowhow_cards[0].source_type == "synthetic_demo",
        "no_connectors": db.query(ConnectorInstance)
        .filter(ConnectorInstance.tenant_id == DEMO_TENANT_ID)
        .count()
        == 0,
        "empty_sidecar_binding": len(sidecar_bindings) == 1
        and all(
            value is None
            for value in (
                sidecar_bindings[0].ragflow_dataset_id,
                sidecar_bindings[0].weknora_kb_id,
                sidecar_bindings[0].pipeshub_org_id,
                sidecar_bindings[0].credentials_ref,
            )
        ),
        "no_sso_secrets": db.query(TenantSSOConfig)
        .filter(TenantSSOConfig.tenant_id == DEMO_TENANT_ID)
        .count()
        == 0,
    }
    return {
        "ok": all(checks.values()),
        "tenant_id": str(DEMO_TENANT_ID),
        "checks": checks,
        "counts": {
            "users": len(users),
            "documents": len(documents),
        },
    }
