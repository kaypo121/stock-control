import uuid
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _default_uuid() -> str:
    return str(uuid.uuid4())


class GatewayPrincipal(Base):
    __tablename__ = "gateway_principals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    principal_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    name = Column(String, nullable=False, index=True)
    principal_type = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False, index=True)
    organization_id = Column(String, nullable=True, index=True)
    workspace_id = Column(String, nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)
    hashed_secret = Column(String, nullable=True)
    permissions_json = Column(Text, nullable=False, default="[]")
    metadata_json = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    last_authenticated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_keys = relationship("GatewayApiKey", back_populates="principal", cascade="all, delete-orphan")
    sessions = relationship("GatewaySession", back_populates="principal", cascade="all, delete-orphan")
    requests = relationship("GatewayRequestLog", back_populates="principal")
    audit_logs = relationship("GatewayAuditLog", back_populates="principal")
    tasks = relationship("GatewayTask", back_populates="principal")
    files = relationship("GatewayFileAsset", back_populates="principal")
    nonces = relationship("GatewayNonce", back_populates="principal", cascade="all, delete-orphan")


class GatewayApiKey(Base):
    __tablename__ = "gateway_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String, nullable=False)
    credential_type = Column(String, nullable=False, default="API_KEY", index=True)
    key_prefix = Column(String, nullable=False, index=True)
    hashed_key = Column(String, nullable=False)
    scopes_json = Column(Text, nullable=False, default="[]")
    metadata_json = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    rotated_from_key_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    principal = relationship("GatewayPrincipal", back_populates="api_keys")


class GatewaySession(Base):
    __tablename__ = "gateway_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    memory_id = Column(String, nullable=True, index=True)
    workspace_id = Column(String, nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)
    organization_id = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    agent_id = Column(String, nullable=True, index=True)
    tool_id = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    trace_id = Column(String, nullable=True, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    principal = relationship("GatewayPrincipal", back_populates="sessions")


class GatewayRequestLog(Base):
    __tablename__ = "gateway_request_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String, unique=True, index=True, nullable=False)
    trace_id = Column(String, nullable=False, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="SET NULL"), nullable=True, index=True)
    http_method = Column(String, nullable=False, index=True)
    path = Column(String, nullable=False, index=True)
    module_name = Column(String, nullable=True, index=True)
    action_name = Column(String, nullable=True, index=True)
    request_body = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    request_size_bytes = Column(Integer, nullable=False, default=0)
    response_size_bytes = Column(Integer, nullable=False, default=0)
    status_code = Column(Integer, nullable=False, index=True)
    success = Column(Boolean, nullable=False, default=False, index=True)
    processing_time_ms = Column(Float, nullable=False, default=0.0)
    error_code = Column(String, nullable=True, index=True)
    caller_ip = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    duplicate_of_request_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    principal = relationship("GatewayPrincipal", back_populates="requests")


class GatewayAuditLog(Base):
    __tablename__ = "gateway_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True, default="INFO")
    action = Column(String, nullable=False, index=True)
    resource = Column(String, nullable=False, index=True)
    result = Column(String, nullable=False, index=True)
    trace_id = Column(String, nullable=True, index=True)
    request_id = Column(String, nullable=True, index=True)
    details_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    principal = relationship("GatewayPrincipal", back_populates="audit_logs")


class GatewayRateLimitBucket(Base):
    __tablename__ = "gateway_rate_limit_buckets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bucket_key = Column(String, unique=True, index=True, nullable=False)
    scope = Column(String, nullable=False, index=True)
    identifier = Column(String, nullable=False, index=True)
    window_name = Column(String, nullable=False, index=True)
    window_started_at = Column(DateTime, nullable=False, index=True)
    request_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class GatewayEvent(Base):
    __tablename__ = "gateway_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    event_type = Column(String, nullable=False, index=True)
    topic = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True, default="PENDING")
    trace_id = Column(String, nullable=True, index=True)
    request_id = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)

    deliveries = relationship("GatewayWebhookDelivery", back_populates="event", cascade="all, delete-orphan")


class GatewayWebhookEndpoint(Base):
    __tablename__ = "gateway_webhook_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    name = Column(String, nullable=False, index=True)
    target_url = Column(String, nullable=False)
    event_types_json = Column(Text, nullable=False, default="[]")
    secret_key = Column(String, nullable=False)
    headers_json = Column(Text, nullable=False, default="{}")
    timeout_seconds = Column(Integer, nullable=False, default=10)
    max_retries = Column(Integer, nullable=False, default=3)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    deliveries = relationship("GatewayWebhookDelivery", back_populates="endpoint", cascade="all, delete-orphan")


class GatewayWebhookDelivery(Base):
    __tablename__ = "gateway_webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    endpoint_id = Column(Integer, ForeignKey("gateway_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("gateway_events.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, index=True, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    endpoint = relationship("GatewayWebhookEndpoint", back_populates="deliveries")
    event = relationship("GatewayEvent", back_populates="deliveries")


class GatewayDeadLetter(Base):
    __tablename__ = "gateway_dead_letters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dead_letter_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    delivery_id = Column(String, nullable=False, index=True)
    reason = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class GatewayTask(Base):
    __tablename__ = "gateway_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="SET NULL"), nullable=True, index=True)
    task_type = Column(String, nullable=False, index=True)
    module_name = Column(String, nullable=False, index=True)
    action_name = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True, default="QUEUED")
    priority = Column(String, nullable=False, index=True, default="normal")
    progress = Column(Float, nullable=False, default=0.0)
    trace_id = Column(String, nullable=True, index=True)
    request_id = Column(String, nullable=True, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    principal = relationship("GatewayPrincipal", back_populates="tasks")


class GatewayFileAsset(Base):
    __tablename__ = "gateway_file_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String, unique=True, index=True, nullable=False, default=_default_uuid)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="SET NULL"), nullable=True, index=True)
    original_name = Column(String, nullable=False)
    content_type = Column(String, nullable=False, index=True)
    extension = Column(String, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    checksum_sha256 = Column(String, nullable=False, index=True)
    storage_path = Column(String, nullable=False, unique=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    principal = relationship("GatewayPrincipal", back_populates="files")


class GatewayNonce(Base):
    __tablename__ = "gateway_nonces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nonce = Column(String, unique=True, index=True, nullable=False)
    principal_id = Column(Integer, ForeignKey("gateway_principals.id", ondelete="CASCADE"), nullable=False, index=True)
    request_signature = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(minutes=5), index=True)
    used_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    principal = relationship("GatewayPrincipal", back_populates="nonces")


class GatewayPlugin(Base):
    __tablename__ = "gateway_plugins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plugin_key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
