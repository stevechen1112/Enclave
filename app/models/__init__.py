from app.db.base_class import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document, DocumentChunk
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.feedback import ChatFeedback
from app.models.audit import AuditLog, UsageRecord
from app.models.permission import Department, FeaturePermission
from app.models.feature_flag import FeatureFlag
# Phase 0: Knowledge Base domain model
from app.models.knowledge_base import (
    KnowledgeBase, KnowledgeBaseMember,
    KnowledgeBaseRevision, DocumentArtifact,
)
# Phase 0: Event sourcing & consistency
from app.models.outbox import (
    OutboxEvent, ProjectionStatus, SyncCursor, DeadLetterEvent,
)
from app.models.gateway_resource import GatewayResource
from app.models.connector import (
    ConnectorInstance, ExternalPrincipal, SourceAclEntry, ConnectorResource,
)
from app.models.wiki import WikiPage, WikiRevision
from app.models.graph import GraphEntity, GraphEdge
from app.models.policy_deny import PolicyDenyEntry
from app.models.agent_approval import AgentApprovalRequest
# Phase 10: Agent models
from app.models.watch_folder import WatchFolder
from app.models.review_item import ReviewItem
# Phase 13: Knowledge Base Maintenance models
from app.models.kb_maintenance import (
    DocumentVersion, Category, CategoryRevision,
    KBBackup, KnowledgeGap, IntegrityReport,
)
# Phase 11-2: Generated Report persistence
from app.models.generated_report import GeneratedReport
from app.models.billing import BillingRecord
from app.models.tenant import TenantSSOConfig
# ADR-013: sidecar 歸屬綁定（未 import 會導致測試 DB create_all 缺表）
from app.models.sidecar_binding import TenantSidecarBinding
# MKA: 製造業知識助理領域模型
from app.models.mka import (
    JobModule, TenantModuleBinding, InteractionSession,
    TenantTermDictionary, FormDefinition, FormInstance,
    RuleSet, ApprovalPolicy, MKAApprovalRequest, KnowhowCardModel,
    MKAAudioPolicy, MKATaskCost, SceneRegistry, JobRole,
    UserJobRoleAssignment, FormTemplate, MKAWriteRequest,
    MKAWriteAudit, MKAEvent, KnowhowLineage, MKAReviewReminder,
)
