from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class GatewayBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class GatewayWarning(GatewayBaseModel):
    code: str
    message: str


class GatewayErrorDetail(GatewayBaseModel):
    code: str
    message: str
    field: Optional[str] = None
    detail: Optional[Any] = None


class GatewayParty(GatewayBaseModel):
    id: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None


class GatewayScopeRef(GatewayBaseModel):
    id: Optional[str] = None
    name: Optional[str] = None


class GatewayContextEnvelope(GatewayBaseModel):
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    memory_id: Optional[str] = Field(default=None, alias="memoryId")
    workspace_id: Optional[str] = Field(default=None, alias="workspaceId")
    project_id: Optional[str] = Field(default=None, alias="projectId")
    organization_id: Optional[str] = Field(default=None, alias="organizationId")
    user_id: Optional[str] = Field(default=None, alias="userId")
    agent_id: Optional[str] = Field(default=None, alias="agentId")
    tool_id: Optional[str] = Field(default=None, alias="toolId")
    correlation_id: Optional[str] = Field(default=None, alias="correlationId")
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GatewayActionEnvelope(GatewayBaseModel):
    module: str
    resource: str
    operation: str
    mode: Literal["sync", "async", "stream"] = "sync"
    provider: Optional[str] = None
    target: Optional[str] = None
    timeout_seconds: int = Field(default=30, alias="timeoutSeconds", ge=1, le=300)


class GatewayRequestEnvelope(GatewayBaseModel):
    request_id: Optional[str] = Field(default=None, alias="requestId")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent: Optional[GatewayParty] = None
    user: Optional[GatewayParty] = None
    workspace: Optional[GatewayScopeRef] = None
    context: GatewayContextEnvelope = Field(default_factory=GatewayContextEnvelope)
    action: GatewayActionEnvelope
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BatchGatewayRequest(GatewayBaseModel):
    requests: List[GatewayRequestEnvelope] = Field(min_length=1, max_length=50)


class GatewayResponseEnvelope(GatewayBaseModel):
    status: str
    success: bool
    message: str
    data: Any = None
    errors: List[GatewayErrorDetail] = Field(default_factory=list)
    warnings: List[GatewayWarning] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    processing_time: float = Field(default=0.0, alias="processingTime")
    trace_id: str = Field(alias="traceId")
    request_id: str = Field(alias="requestId")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str


class PrincipalRegistrationRequest(GatewayBaseModel):
    name: str
    principal_type: Literal["ADMIN", "MANAGER", "EMPLOYEE", "AI_AGENT", "AUTOMATION_SERVICE", "THIRD_PARTY", "READ_ONLY"]
    role: str
    permissions: List[str] = Field(default_factory=list)
    organization_id: Optional[str] = Field(default=None, alias="organizationId")
    workspace_id: Optional[str] = Field(default=None, alias="workspaceId")
    project_id: Optional[str] = Field(default=None, alias="projectId")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    secret: Optional[str] = Field(default=None, min_length=16)


class PrincipalResponse(GatewayBaseModel):
    principal_id: str = Field(alias="principalId")
    name: str
    principal_type: str = Field(alias="principalType")
    role: str
    permissions: List[str]
    organization_id: Optional[str] = Field(default=None, alias="organizationId")
    workspace_id: Optional[str] = Field(default=None, alias="workspaceId")
    project_id: Optional[str] = Field(default=None, alias="projectId")
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")


class ApiKeyCreateRequest(GatewayBaseModel):
    principal_id: str = Field(alias="principalId")
    label: str
    credential_type: Literal["API_KEY", "SERVICE_TOKEN", "MACHINE_TOKEN"] = Field(default="API_KEY", alias="credentialType")
    scopes: List[str] = Field(default_factory=list)
    expires_in_days: int = Field(default=90, alias="expiresInDays", ge=1, le=365)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApiKeyResponse(GatewayBaseModel):
    key_id: str = Field(alias="keyId")
    principal_id: str = Field(alias="principalId")
    label: str
    credential_type: str = Field(alias="credentialType")
    key_prefix: str = Field(alias="keyPrefix")
    plain_text_secret: Optional[str] = Field(default=None, alias="plainTextSecret")
    scopes: List[str]
    expires_at: Optional[datetime] = Field(default=None, alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")


class TokenRequest(GatewayBaseModel):
    principal_id: str = Field(alias="principalId")
    client_secret: str = Field(alias="clientSecret")
    grant_type: Literal["client_credentials", "password", "service_token"] = Field(default="client_credentials", alias="grantType")
    scopes: List[str] = Field(default_factory=list)


class TokenResponse(GatewayBaseModel):
    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    scope: str
    principal_id: str = Field(alias="principalId")
    role: str


class RotateCredentialResponse(GatewayBaseModel):
    old_key_id: str = Field(alias="oldKeyId")
    new_credential: ApiKeyResponse = Field(alias="newCredential")


class EventPublishRequest(GatewayBaseModel):
    event_type: str = Field(alias="eventType")
    topic: str
    source: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventResponse(GatewayBaseModel):
    event_id: str = Field(alias="eventId")
    event_type: str = Field(alias="eventType")
    topic: str
    source: str
    status: str
    created_at: datetime = Field(alias="createdAt")


class WebhookRegistrationRequest(GatewayBaseModel):
    name: str
    target_url: HttpUrl = Field(alias="targetUrl")
    event_types: List[str] = Field(alias="eventTypes", min_length=1)
    secret_key: str = Field(alias="secretKey", min_length=16)
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, alias="timeoutSeconds", ge=1, le=60)
    max_retries: int = Field(default=3, alias="maxRetries", ge=0, le=10)


class WebhookEndpointResponse(GatewayBaseModel):
    webhook_id: str = Field(alias="webhookId")
    name: str
    target_url: str = Field(alias="targetUrl")
    event_types: List[str] = Field(alias="eventTypes")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    max_retries: int = Field(alias="maxRetries")
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")


class TaskCreateRequest(GatewayBaseModel):
    request: GatewayRequestEnvelope
    priority: Literal["low", "normal", "high"] = "normal"
    task_type: Literal["BACKGROUND_JOB", "LONG_RUNNING_TASK", "BATCH_JOB"] = Field(default="BACKGROUND_JOB", alias="taskType")


class TaskResponse(GatewayBaseModel):
    task_id: str = Field(alias="taskId")
    task_type: str = Field(alias="taskType")
    module_name: str = Field(alias="moduleName")
    action_name: str = Field(alias="actionName")
    status: str
    priority: str
    progress: float
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    request_id: Optional[str] = Field(default=None, alias="requestId")
    result: Optional[Any] = None
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ChatMessage(GatewayBaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(GatewayBaseModel):
    provider: str
    model: str
    messages: List[ChatMessage] = Field(min_length=1)
    stream: bool = False
    context: GatewayContextEnvelope = Field(default_factory=GatewayContextEnvelope)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRequest(GatewayBaseModel):
    tool_name: str = Field(alias="toolName")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    context: GatewayContextEnvelope = Field(default_factory=GatewayContextEnvelope)


class FileMetadataResponse(GatewayBaseModel):
    file_id: str = Field(alias="fileId")
    original_name: str = Field(alias="originalName")
    content_type: str = Field(alias="contentType")
    extension: str
    size_bytes: int = Field(alias="sizeBytes")
    checksum_sha256: str = Field(alias="checksumSha256")
    created_at: datetime = Field(alias="createdAt")


class HealthStatusResponse(GatewayBaseModel):
    service: str
    status: str
    version: str
    database: Dict[str, Any]
    cache: Dict[str, Any]
    queue: Dict[str, Any]
    metrics: Dict[str, Any]


class VersionResponse(GatewayBaseModel):
    service: str
    version: str
    supported_protocols: List[str] = Field(alias="supportedProtocols")
    supported_auth: List[str] = Field(alias="supportedAuth")
    plugin_support: bool = Field(alias="pluginSupport")


class ContextSnapshotResponse(GatewayBaseModel):
    session_id: str = Field(alias="sessionId")
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
    memory_id: Optional[str] = Field(default=None, alias="memoryId")
    workspace_id: Optional[str] = Field(default=None, alias="workspaceId")
    project_id: Optional[str] = Field(default=None, alias="projectId")
    organization_id: Optional[str] = Field(default=None, alias="organizationId")
    user_id: Optional[str] = Field(default=None, alias="userId")
    agent_id: Optional[str] = Field(default=None, alias="agentId")
    tool_id: Optional[str] = Field(default=None, alias="toolId")
    correlation_id: Optional[str] = Field(default=None, alias="correlationId")
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    metadata: Dict[str, Any]
    updated_at: datetime = Field(alias="updatedAt")


class PluginResponse(GatewayBaseModel):
    plugin_key: str = Field(alias="pluginKey")
    name: str
    version: str
    enabled: bool
    capabilities: List[str]
