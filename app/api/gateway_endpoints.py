import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.gateway_models import GatewayPrincipal, GatewaySession
from app.schemas.gateway_schemas import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    BatchGatewayRequest,
    ChatCompletionRequest,
    ContextSnapshotResponse,
    EventPublishRequest,
    FileMetadataResponse,
    GatewayErrorDetail,
    GatewayRequestEnvelope,
    GatewayResponseEnvelope,
    HealthStatusResponse,
    PluginResponse,
    PrincipalRegistrationRequest,
    PrincipalResponse,
    RotateCredentialResponse,
    TaskCreateRequest,
    TaskResponse,
    TokenRequest,
    TokenResponse,
    ToolExecutionRequest,
    VersionResponse,
    WebhookEndpointResponse,
    WebhookRegistrationRequest,
)
from app.services.ai_provider_service import provider_service
from app.services.gateway_security import GatewayAPIError, GatewaySecurityService
from app.services.gateway_service import (
    event_service,
    file_service,
    gateway_orchestrator,
    metrics_service,
    plugin_registry,
    render_stream_chunks,
    task_service,
    webhook_service,
    json_loads,
)


router = APIRouter(prefix="/v1", tags=["AI Gateway"])
security_service = GatewaySecurityService()


def _response(
    request: Request,
    status_text: str,
    success: bool,
    message: str,
    data: Any = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> JSONResponse:
    started_at = getattr(request.state, "started_at", None)
    processing_ms = 0.0
    if started_at is not None:
        processing_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
    body = GatewayResponseEnvelope(
        status=status_text,
        success=success,
        message=message,
        data=data,
        errors=[GatewayErrorDetail(**item) for item in (errors or [])],
        warnings=warnings or [],
        metadata=metadata or {},
        processingTime=processing_ms,
        traceId=getattr(request.state, "trace_id", request.headers.get("X-Trace-Id", "")),
        requestId=getattr(request.state, "request_id", request.headers.get("X-Request-Id", "")),
        version="v1",
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(by_alias=True, mode="json"))


def _caller_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _authenticate(db: Session, request: Request, required_permissions: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    identity = security_service.authenticate_request(db, request)
    if required_permissions:
        security_service.require_permissions(identity, required_permissions)
    return identity


def _task_to_response(task) -> TaskResponse:
    return TaskResponse(
        taskId=task.task_id,
        taskType=task.task_type,
        moduleName=task.module_name,
        actionName=task.action_name,
        status=task.status,
        priority=task.priority,
        progress=task.progress,
        traceId=task.trace_id,
        requestId=task.request_id,
        result=json_loads(task.result_json, None),
        errorMessage=task.error_message,
        createdAt=task.created_at,
        updatedAt=task.updated_at,
    )


@router.on_event("startup")
def bootstrap_gateway() -> None:
    db = next(get_db())
    try:
        gateway_orchestrator.bootstrap(db)
    finally:
        db.close()


@router.post("/auth/principals")
def register_principal(payload: PrincipalRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    existing_principals = db.query(GatewayPrincipal).count()
    if existing_principals > 0:
        _authenticate(db, request, ["gateway:write"])
    principal, secret = security_service.create_principal(db, payload)
    response = PrincipalResponse(
        principalId=principal.principal_id,
        name=principal.name,
        principalType=principal.principal_type,
        role=principal.role,
        permissions=json_loads(principal.permissions_json, []),
        organizationId=principal.organization_id,
        workspaceId=principal.workspace_id,
        projectId=principal.project_id,
        isActive=principal.is_active,
        createdAt=principal.created_at,
    )
    return _response(
        request,
        status_text="created",
        success=True,
        message="Gateway principal registered.",
        data={"principal": response.model_dump(by_alias=True), "clientSecret": secret},
        status_code=201,
    )


@router.post("/auth/api-keys")
def create_api_key(payload: ApiKeyCreateRequest, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:write"])
    api_key, plain_secret, principal = security_service.create_api_key(db, payload)
    response = ApiKeyResponse(
        keyId=api_key.key_id,
        principalId=principal.principal_id,
        label=api_key.label,
        credentialType=api_key.credential_type,
        keyPrefix=api_key.key_prefix,
        plainTextSecret=plain_secret,
        scopes=json_loads(api_key.scopes_json, []),
        expiresAt=api_key.expires_at,
        createdAt=api_key.created_at,
    )
    return _response(request, "created", True, "Gateway credential created.", data=response.model_dump(by_alias=True), status_code=201)


@router.post("/auth/token")
def issue_token(payload: TokenRequest, request: Request, db: Session = Depends(get_db)):
    token = security_service.issue_token(db, payload)
    response = TokenResponse(**token)
    return _response(request, "ok", True, "Access token issued.", data=response.model_dump(by_alias=True))


@router.post("/auth/api-keys/{key_id}/rotate")
def rotate_api_key(key_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:write"])
    old_key, new_key, plain_secret = security_service.rotate_api_key(db, key_id)
    rotated = RotateCredentialResponse(
        oldKeyId=old_key.key_id,
        newCredential=ApiKeyResponse(
            keyId=new_key.key_id,
            principalId=old_key.principal.principal_id,
            label=new_key.label,
            credentialType=new_key.credential_type,
            keyPrefix=new_key.key_prefix,
            plainTextSecret=plain_secret,
            scopes=json_loads(new_key.scopes_json, []),
            expiresAt=new_key.expires_at,
            createdAt=new_key.created_at,
        ),
    )
    return _response(request, "ok", True, "Gateway credential rotated.", data=rotated.model_dump(by_alias=True))


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    response = HealthStatusResponse(**metrics_service.health(db))
    return _response(request, "ok", True, "Gateway health is available.", data=response.model_dump(by_alias=True))


@router.get("/status")
def status_endpoint(request: Request, db: Session = Depends(get_db)):
    return _response(request, "ok", True, "Gateway status is available.", data=metrics_service.status(db))


@router.get("/version")
def version(request: Request):
    response = VersionResponse(
        service="agriculture-ai-gateway",
        version="1.0.0",
        supportedProtocols=["REST", "WebSocket", "SSE", "StreamingResponse"],
        supportedAuth=["JWT", "API Keys", "Bearer Tokens", "Service Tokens", "Machine Tokens", "OAuth2-compatible client credentials"],
        pluginSupport=True,
    )
    return _response(request, "ok", True, "Gateway version metadata returned.", data=response.model_dump(by_alias=True))


@router.get("/plugins")
def list_plugins(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    plugins = [PluginResponse(**item).model_dump(by_alias=True) for item in plugin_registry.describe()]
    return _response(request, "ok", True, "Gateway plugins listed.", data={"plugins": plugins})


@router.get("/ai/providers")
def list_ai_providers(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    return _response(request, "ok", True, "AI providers listed.", data={"providers": provider_service.catalog()})


@router.get("/ai/models")
def list_ai_models(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    return _response(request, "ok", True, "AI model catalog listed.", data={"providers": provider_service.model_catalog()})


@router.post("/ai/execute")
async def execute_ai_request(payload: GatewayRequestEnvelope, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, gateway_orchestrator.required_permissions(payload))
    body = await security_service.validate_request_body(request)
    security_service.validate_request_signature(db, identity, body, request)
    security_service.apply_rate_limit(db, request, identity)
    result = gateway_orchestrator.process_gateway_request(
        db=db,
        request=payload,
        http_method=request.method,
        path=request.url.path,
        identity=identity,
        request_id=payload.request_id or request.state.request_id,
        trace_id=payload.context.trace_id or request.state.trace_id,
        caller_ip=_caller_ip(request),
    )
    return _response(request, "ok", True, "Gateway request processed.", data=result)


@router.post("/actions/execute")
async def execute_action(payload: GatewayRequestEnvelope, request: Request, db: Session = Depends(get_db)):
    return await execute_ai_request(payload, request, db)


@router.post("/ai/batch")
async def batch_execute(payload: BatchGatewayRequest, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, ["gateway:write"])
    body = await security_service.validate_request_body(request)
    security_service.validate_request_signature(db, identity, body, request)
    security_service.apply_rate_limit(db, request, identity)
    results = []
    for item in payload.requests:
        try:
            security_service.require_permissions(identity, gateway_orchestrator.required_permissions(item))
            result = gateway_orchestrator.process_gateway_request(
                db=db,
                request=item,
                http_method=request.method,
                path=request.url.path,
                identity=identity,
                request_id=item.request_id or f"{request.state.request_id}-{len(results)}",
                trace_id=item.context.trace_id or request.state.trace_id,
                caller_ip=_caller_ip(request),
                allow_duplicate=True,
            )
            results.append({"requestId": item.request_id, "success": True, "data": result})
        except GatewayAPIError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "BATCH_ERROR", "message": str(exc.detail)}
            results.append({"requestId": item.request_id, "success": False, "error": detail})
    return _response(request, "ok", True, "Batch gateway request processed.", data={"results": results})


@router.post("/ai/stream")
async def stream_ai_request(payload: GatewayRequestEnvelope, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, gateway_orchestrator.required_permissions(payload))
    security_service.apply_rate_limit(db, request, identity)
    result = gateway_orchestrator.process_gateway_request(
        db=db,
        request=payload,
        http_method=request.method,
        path=request.url.path,
        identity=identity,
        request_id=payload.request_id or request.state.request_id,
        trace_id=payload.context.trace_id or request.state.trace_id,
        caller_ip=_caller_ip(request),
        allow_duplicate=True,
    )

    async def event_stream():
        for chunk in render_stream_chunks(result):
            yield f"data: {chunk}\n\n"
            await asyncio.sleep(0.01)
        yield "event: complete\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/ai/notifications/stream")
async def notifications_stream(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])

    async def event_stream():
        for _ in range(3):
            events = event_service.list_events(db, limit=5)
            payload = [
                {
                    "eventId": event.event_id,
                    "eventType": event.event_type,
                    "topic": event.topic,
                    "source": event.source,
                    "status": event.status,
                    "createdAt": event.created_at.isoformat(),
                }
                for event in events
            ]
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1)
        yield "event: complete\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    await websocket.accept()
    try:
        await websocket.send_json({"type": "gateway.connected", "message": "WebSocket notifications ready."})
        while True:
            payload = await websocket.receive_text()
            await websocket.send_json({"type": "gateway.echo", "payload": payload})
    except WebSocketDisconnect:
        return


@router.post("/chat/completions")
@router.post("/ai/chat/completions")
async def chat_completions(payload: ChatCompletionRequest, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, ["gateway:write"])
    body = await security_service.validate_request_body(request)
    security_service.validate_request_signature(db, identity, body, request)
    security_service.apply_rate_limit(db, request, identity)
    provider = provider_service.require_provider(payload.provider)
    summary = {
        "provider": provider["canonicalName"],
        "model": payload.model,
        "messageCount": len(payload.messages),
        "stream": payload.stream,
        "context": payload.context.model_dump(by_alias=True),
        "preview": payload.messages[-1].content[:200],
    }
    event = event_service.publish(
        db,
        event_type="ai.chat.received",
        topic="chat.completions",
        source=provider["canonicalName"],
        payload=summary,
        trace_id=payload.context.trace_id or request.state.trace_id,
        request_id=request.state.request_id,
        correlation_id=payload.context.correlation_id,
    )
    if payload.stream:
        async def stream():
            yield f"data: {json.dumps({'eventId': event.event_id, 'status': 'accepted', 'provider': provider['canonicalName']})}\n\n"
            async for chunk in provider_service.stream_chat_completion(
                payload=payload,
                request_id=request.state.request_id,
                trace_id=payload.context.trace_id or request.state.trace_id,
            ):
                yield chunk

        return StreamingResponse(stream(), media_type="text/event-stream")
    completion = await provider_service.chat_completion(
        payload=payload,
        request_id=request.state.request_id,
        trace_id=payload.context.trace_id or request.state.trace_id,
    )
    completed_event = event_service.publish(
        db,
        event_type="ai.chat.completed",
        topic="chat.completions",
        source=provider["canonicalName"],
        payload={
            "eventId": event.event_id,
            "provider": provider["canonicalName"],
            "model": completion["model"],
            "finishReason": completion.get("finishReason"),
        },
        trace_id=payload.context.trace_id or request.state.trace_id,
        request_id=request.state.request_id,
        correlation_id=payload.context.correlation_id,
    )
    return _response(
        request,
        "ok",
        True,
        "Chat completion processed by the gateway.",
        data={"eventId": event.event_id, "completionEventId": completed_event.event_id, **completion},
    )


@router.post("/agents/register")
def register_agent(payload: PrincipalRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    agent_payload = payload.model_copy(update={"principal_type": "AI_AGENT"})
    return register_principal(agent_payload, request, db)


@router.get("/agents")
def list_agents(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    agents = db.query(GatewayPrincipal).filter(GatewayPrincipal.principal_type == "AI_AGENT").all()
    data = [
        PrincipalResponse(
            principalId=agent.principal_id,
            name=agent.name,
            principalType=agent.principal_type,
            role=agent.role,
            permissions=json_loads(agent.permissions_json, []),
            organizationId=agent.organization_id,
            workspaceId=agent.workspace_id,
            projectId=agent.project_id,
            isActive=agent.is_active,
            createdAt=agent.created_at,
        ).model_dump(by_alias=True)
        for agent in agents
    ]
    return _response(request, "ok", True, "Gateway agents listed.", data={"agents": data})


@router.post("/tasks")
def create_task(payload: TaskCreateRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, ["tasks:manage", "gateway:write"])
    task = task_service.create_task(
        db=db,
        request=payload.request,
        identity=identity,
        priority=payload.priority,
        task_type=payload.task_type,
        trace_id=payload.request.context.trace_id or request.state.trace_id,
        request_id=payload.request.request_id or request.state.request_id,
    )
    background_tasks.add_task(task_service.process_task_background, task.task_id)
    return _response(request, "accepted", True, "Gateway task queued.", data=_task_to_response(task).model_dump(by_alias=True), status_code=202)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["tasks:read", "gateway:read"])
    task = task_service.get_task(db, task_id)
    return _response(request, "ok", True, "Gateway task status returned.", data=_task_to_response(task).model_dump(by_alias=True))


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["tasks:manage", "gateway:write"])
    task = task_service.cancel_task(db, task_id)
    return _response(request, "ok", True, "Gateway task updated.", data=_task_to_response(task).model_dump(by_alias=True))


@router.post("/tools/execute")
async def execute_tool(payload: ToolExecutionRequest, request: Request, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, ["tools:execute", "gateway:write"])
    if payload.tool_name == "inventory_lookup":
        envelope = GatewayRequestEnvelope(
            requestId=request.state.request_id,
            context=payload.context,
            action={"module": "stock", "resource": "inventory", "operation": "snapshot"},
            payload=payload.arguments,
        )
        result = gateway_orchestrator.process_gateway_request(
            db=db,
            request=envelope,
            http_method=request.method,
            path=request.url.path,
            identity=identity,
            request_id=envelope.request_id or request.state.request_id,
            trace_id=envelope.context.trace_id or request.state.trace_id,
            caller_ip=_caller_ip(request),
            allow_duplicate=True,
        )
        return _response(request, "ok", True, "Gateway tool executed.", data=result)
    raise GatewayAPIError(404, "TOOL_NOT_FOUND", "Requested gateway tool is not registered.")


@router.get("/context/{session_id}")
def get_context(session_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    context = db.query(GatewaySession).filter(GatewaySession.session_id == session_id).first()
    if not context:
        raise GatewayAPIError(404, "CONTEXT_NOT_FOUND", "Context session was not found.")
    response = ContextSnapshotResponse(
        sessionId=context.session_id,
        conversationId=context.conversation_id,
        memoryId=context.memory_id,
        workspaceId=context.workspace_id,
        projectId=context.project_id,
        organizationId=context.organization_id,
        userId=context.user_id,
        agentId=context.agent_id,
        toolId=context.tool_id,
        correlationId=context.correlation_id,
        traceId=context.trace_id,
        metadata=json_loads(context.metadata_json, {}),
        updatedAt=context.updated_at,
    )
    return _response(request, "ok", True, "Gateway context returned.", data=response.model_dump(by_alias=True))


@router.get("/workspaces/{workspace_id}/context")
def get_workspace_context(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    sessions = db.query(GatewaySession).filter(GatewaySession.workspace_id == workspace_id).all()
    return _response(request, "ok", True, "Workspace context snapshot returned.", data={"sessions": [item.session_id for item in sessions]})


@router.get("/projects/{project_id}/context")
def get_project_context(project_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    sessions = db.query(GatewaySession).filter(GatewaySession.project_id == project_id).all()
    return _response(request, "ok", True, "Project context snapshot returned.", data={"sessions": [item.session_id for item in sessions]})


@router.get("/users/{user_id}/context")
def get_user_context(user_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    sessions = db.query(GatewaySession).filter(GatewaySession.user_id == user_id).all()
    return _response(request, "ok", True, "User context snapshot returned.", data={"sessions": [item.session_id for item in sessions]})


@router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), request: Request = None, db: Session = Depends(get_db)):
    identity = _authenticate(db, request, ["files:write", "gateway:write"])
    asset = await file_service.store_file(db, file, identity["principal"].id if identity else None)
    response = FileMetadataResponse(
        fileId=asset.file_id,
        originalName=asset.original_name,
        contentType=asset.content_type,
        extension=asset.extension,
        sizeBytes=asset.size_bytes,
        checksumSha256=asset.checksum_sha256,
        createdAt=asset.created_at,
    )
    return _response(request, "created", True, "Gateway file stored.", data=response.model_dump(by_alias=True), status_code=201)


@router.get("/files/{file_id}")
def get_file(file_id: str, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["files:read", "gateway:read"])
    asset = file_service.get_asset(db, file_id)
    return FileResponse(asset.storage_path, media_type=asset.content_type, filename=asset.original_name)


@router.post("/webhooks")
def register_webhook(payload: WebhookRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["webhooks:manage", "gateway:write"])
    endpoint = webhook_service.register(db, payload.model_dump(by_alias=True))
    response = WebhookEndpointResponse(
        webhookId=endpoint.webhook_id,
        name=endpoint.name,
        targetUrl=endpoint.target_url,
        eventTypes=json_loads(endpoint.event_types_json, []),
        timeoutSeconds=endpoint.timeout_seconds,
        maxRetries=endpoint.max_retries,
        isActive=endpoint.is_active,
        createdAt=endpoint.created_at,
    )
    return _response(request, "created", True, "Webhook endpoint registered.", data=response.model_dump(by_alias=True), status_code=201)


@router.get("/webhooks")
def list_webhooks(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["webhooks:manage", "gateway:read"])
    endpoints = webhook_service.list_endpoints(db)
    data = [
        WebhookEndpointResponse(
            webhookId=endpoint.webhook_id,
            name=endpoint.name,
            targetUrl=endpoint.target_url,
            eventTypes=json_loads(endpoint.event_types_json, []),
            timeoutSeconds=endpoint.timeout_seconds,
            maxRetries=endpoint.max_retries,
            isActive=endpoint.is_active,
            createdAt=endpoint.created_at,
        ).model_dump(by_alias=True)
        for endpoint in endpoints
    ]
    return _response(request, "ok", True, "Webhook endpoints listed.", data={"webhooks": data})


@router.post("/events")
def publish_event(payload: EventPublishRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["events:publish", "gateway:write"])
    event = event_service.publish(
        db=db,
        event_type=payload.event_type,
        topic=payload.topic,
        source=payload.source,
        payload=payload.payload,
        metadata=payload.metadata,
        trace_id=request.state.trace_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )
    background_tasks.add_task(webhook_service.dispatch_event, event.event_id)
    return _response(
        request,
        "created",
        True,
        "Gateway event published.",
        data={
            "eventId": event.event_id,
            "eventType": event.event_type,
            "topic": event.topic,
            "source": event.source,
            "status": event.status,
            "createdAt": event.created_at.isoformat(),
        },
        status_code=201,
    )


@router.get("/events")
def list_events(request: Request, db: Session = Depends(get_db)):
    _authenticate(db, request, ["gateway:read"])
    events = event_service.list_events(db)
    data = [
        {
            "eventId": event.event_id,
            "eventType": event.event_type,
            "topic": event.topic,
            "source": event.source,
            "status": event.status,
            "createdAt": event.created_at.isoformat(),
        }
        for event in events
    ]
    return _response(request, "ok", True, "Gateway events listed.", data={"events": data})
