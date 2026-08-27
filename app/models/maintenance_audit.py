"""Append-only audit record for privileged cross-tenant maintenance."""

from sqlalchemy import JSON, BigInteger, Column, DateTime, Identity, Text, func, text

from app.db.base_class import Base


class PlatformMaintenanceAudit(Base):
    __tablename__ = "platform_maintenance_audit"

    id = Column(BigInteger, Identity(), primary_key=True)
    occurred_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    db_role = Column(Text, server_default=text("current_user"), nullable=False)
    actor_identity = Column(Text, nullable=False)
    operation = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    correlation_id = Column(Text, nullable=True)
    metadata_json = Column(JSON, server_default=text("'{}'::json"), nullable=False)
