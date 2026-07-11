import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _default_uuid() -> str:
    return str(uuid.uuid4())


class GatewayPrincipal(Base):
    __tablename__ = "gateway_principals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    principal_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    principal_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False, index=True)
    organization_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    hashed_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    api_keys: Mapped[list["GatewayApiKey"]] = relationship(
        "GatewayApiKey",
        back_populates="principal",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["GatewaySession"]] = relationship(
        "GatewaySession",
        back_populates="principal",
        cascade="all, delete-orphan",
    )
    requests: Mapped[list["GatewayRequestLog"]] = relationship("GatewayRequestLog", back_populates="principal")
    audit_logs: Mapped[list["GatewayAuditLog"]] = relationship("GatewayAuditLog", back_populates="principal")
    tasks: Mapped[list["GatewayTask"]] = relationship("GatewayTask", back_populates="principal")
    files: Mapped[list["GatewayFileAsset"]] = relationship("GatewayFileAsset", back_populates="principal")
    nonces: Mapped[list["GatewayNonce"]] = relationship(
        "GatewayNonce",
        back_populates="principal",
        cascade="all, delete-orphan",
    )


class GatewayApiKey(Base):
    __tablename__ = "gateway_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    principal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    credential_type: Mapped[str] = mapped_column(String, nullable=False, default="API_KEY", index=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hashed_key: Mapped[str] = mapped_column(String, nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rotated_from_key_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    principal: Mapped["GatewayPrincipal"] = relationship("GatewayPrincipal", back_populates="api_keys")


class GatewaySession(Base):
    __tablename__ = "gateway_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    principal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    memory_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    tool_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    principal: Mapped["GatewayPrincipal | None"] = relationship("GatewayPrincipal", back_populates="sessions")


class GatewayRequestLog(Base):
    __tablename__ = "gateway_request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    principal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    http_method: Mapped[str] = mapped_column(String, nullable=False, index=True)
    path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    module_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    processing_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    caller_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    duplicate_of_request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    principal: Mapped["GatewayPrincipal | None"] = relationship("GatewayPrincipal", back_populates="requests")


class GatewayAuditLog(Base):
    __tablename__ = "gateway_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    principal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, index=True, default="INFO")
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String, nullable=False, index=True)
    result: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    principal: Mapped["GatewayPrincipal | None"] = relationship("GatewayPrincipal", back_populates="audit_logs")


class GatewayRateLimitBucket(Base):
    __tablename__ = "gateway_rate_limit_buckets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False, index=True)
    identifier: Mapped[str] = mapped_column(String, nullable=False, index=True)
    window_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )


class GatewayEvent(Base):
    __tablename__ = "gateway_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True, default="PENDING")
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    deliveries: Mapped[list["GatewayWebhookDelivery"]] = relationship(
        "GatewayWebhookDelivery",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class GatewayWebhookEndpoint(Base):
    __tablename__ = "gateway_webhook_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_url: Mapped[str] = mapped_column(String, nullable=False)
    event_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    secret_key: Mapped[str] = mapped_column(String, nullable=False)
    headers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    deliveries: Mapped[list["GatewayWebhookDelivery"]] = relationship(
        "GatewayWebhookDelivery",
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )


class GatewayWebhookDelivery(Base):
    __tablename__ = "gateway_webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    endpoint_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gateway_webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gateway_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, index=True, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    endpoint: Mapped["GatewayWebhookEndpoint"] = relationship("GatewayWebhookEndpoint", back_populates="deliveries")
    event: Mapped["GatewayEvent"] = relationship("GatewayEvent", back_populates="deliveries")


class GatewayDeadLetter(Base):
    __tablename__ = "gateway_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dead_letter_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    delivery_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class GatewayTask(Base):
    __tablename__ = "gateway_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    principal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    module_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True, default="QUEUED")
    priority: Mapped[str] = mapped_column(String, nullable=False, index=True, default="normal")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    principal: Mapped["GatewayPrincipal | None"] = relationship("GatewayPrincipal", back_populates="tasks")


class GatewayFileAsset(Base):
    __tablename__ = "gateway_file_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_default_uuid
    )
    principal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    extension: Mapped[str] = mapped_column(String, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    principal: Mapped["GatewayPrincipal | None"] = relationship("GatewayPrincipal", back_populates="files")


class GatewayNonce(Base):
    __tablename__ = "gateway_nonces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nonce: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    principal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gateway_principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_signature: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(minutes=5),
        index=True,
    )
    used_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    principal: Mapped["GatewayPrincipal"] = relationship("GatewayPrincipal", back_populates="nonces")


class GatewayPlugin(Base):
    __tablename__ = "gateway_plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )
