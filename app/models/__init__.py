from app.db.base_class import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document, DocumentChunk
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.feedback import ChatFeedback
from app.models.audit import AuditLog, UsageRecord
from app.models.permission import Department, FeaturePermission
from app.models.feature_flag import FeatureFlag
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
