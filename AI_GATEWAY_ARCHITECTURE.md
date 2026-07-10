# AI Gateway Architecture

## Purpose

The AI Gateway is the machine-to-machine entry point for the platform. It centralizes authentication, authorization, request validation, context propagation, provider routing, observability, rate limiting, event delivery, file exchange, and plugin-based module access.

## Why This Design

- **FastAPI + SQLAlchemy** keeps the service compatible with the existing backend and deployment targets.
- **Gateway router under `/v1`** provides a stable versioned contract for agents, AI providers, automation services, and partner integrations.
- **Provider adapter service** isolates upstream LLM differences behind one normalized chat-completions interface.
- **Plugin registry** keeps internal platform access modular so new modules can be added without changing the request contract.
- **Standard request and response envelopes** make tracing, auditing, and client integration predictable.
- **Database-backed logs, tasks, events, and rate limits** preserve operational state across processes.

## Runtime Architecture

1. A caller sends a request to `/v1/...`.
2. Middleware injects `requestId`, `traceId`, `correlationId`, processing timers, security headers, and IP allow-list enforcement.
3. Security services validate credentials, signatures, body size, permissions, and rate limits.
4. The gateway either:
   - routes the request to an internal plugin for platform actions, or
   - routes chat completions to an upstream AI provider adapter.
5. The orchestrator persists context sessions, request logs, audit logs, events, tasks, and files.
6. The gateway returns a standardized response envelope with trace metadata.

## Folder Structure

```text
app/
  api/
    endpoints.py
    gateway_endpoints.py
    integration_endpoints.py
    quality_endpoints.py
  middleware/
    gateway_middleware.py
  models/
    gateway_models.py
    integration_models.py
    quality_models.py
    stock_models.py
  repositories/
    stock_repo.py
  schemas/
    gateway_schemas.py
    integration_schemas.py
    quality_schemas.py
    stock_schemas.py
  services/
    ai_provider_service.py
    forecast_service.py
    gateway_security.py
    gateway_service.py
    import_service.py
    integration_service.py
    quality_service.py
    stock_service.py
  config.py
  database.py
  main.py
tests/
  conftest.py
  test_gateway_api.py
  test_stock_control.py
AI_GATEWAY_ARCHITECTURE.md
generate_openapi.py
requirements.txt
render.yaml
Procfile
vercel.json
```

## Gateway Endpoints

- `POST /v1/auth/principals`
- `POST /v1/auth/api-keys`
- `POST /v1/auth/token`
- `POST /v1/auth/api-keys/{key_id}/rotate`
- `GET /v1/health`
- `GET /v1/status`
- `GET /v1/version`
- `GET /v1/plugins`
- `GET /v1/ai/providers`
- `GET /v1/ai/models`
- `POST /v1/ai/execute`
- `POST /v1/ai/batch`
- `POST /v1/ai/stream`
- `GET /v1/ai/notifications/stream`
- `POST /v1/chat/completions`
- `POST /v1/ai/chat/completions`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `POST /v1/tasks/{task_id}/cancel`
- `POST /v1/tools/execute`
- `GET /v1/context/{session_id}`
- `GET /v1/workspaces/{workspace_id}/context`
- `GET /v1/projects/{project_id}/context`
- `GET /v1/users/{user_id}/context`
- `POST /v1/files/upload`
- `GET /v1/files/{file_id}`
- `POST /v1/webhooks`
- `GET /v1/webhooks`
- `POST /v1/events`
- `GET /v1/events`
- `GET /v1/agents`
- `POST /v1/agents/register`

## Standard Request Envelope

```json
{
  "requestId": "req_123",
  "timestamp": "2026-07-10T12:00:00Z",
  "agent": {
    "id": "agent_1",
    "type": "AI_AGENT",
    "name": "planner",
    "role": "AUTOMATION_SERVICE"
  },
  "user": {
    "id": "user_1",
    "type": "human"
  },
  "workspace": {
    "id": "workspace_1",
    "name": "default"
  },
  "context": {
    "conversationId": "conv_1",
    "sessionId": "sess_1",
    "memoryId": "mem_1",
    "workspaceId": "workspace_1",
    "projectId": "project_1",
    "organizationId": "org_1",
    "userId": "user_1",
    "agentId": "agent_1",
    "toolId": "tool_1",
    "correlationId": "corr_1",
    "traceId": "trace_1"
  },
  "action": {
    "module": "stock",
    "resource": "inventory",
    "operation": "snapshot",
    "mode": "sync"
  },
  "payload": {},
  "metadata": {}
}
```

## Standard Response Envelope

```json
{
  "status": "ok",
  "success": true,
  "message": "Gateway request processed.",
  "data": {},
  "errors": [],
  "warnings": [],
  "metadata": {},
  "processingTime": 12.4,
  "traceId": "trace_1",
  "requestId": "req_123",
  "timestamp": "2026-07-10T12:00:00Z",
  "version": "v1"
}
```

## Authentication and Authorization

- JWT bearer tokens for machine clients.
- API keys, service tokens, and machine tokens.
- Per-role permissions with custom permission overrides.
- Signature verification using `X-Signature`, `X-Nonce`, and `X-Timestamp`.
- Replay attack protection using persisted nonces.
- Rate limits enforced per principal and per organization.

## Supported AI Providers

- OpenAI / ChatGPT
- Anthropic / Claude
- Google Gemini
- DeepSeek
- xAI / Grok
- OpenRouter
- Ollama
- Custom OpenAI-compatible providers

## Database Schema

The gateway persists these operational tables:

- `gateway_principals`
- `gateway_api_keys`
- `gateway_sessions`
- `gateway_request_logs`
- `gateway_audit_logs`
- `gateway_rate_limit_buckets`
- `gateway_events`
- `gateway_webhook_endpoints`
- `gateway_webhook_deliveries`
- `gateway_dead_letters`
- `gateway_tasks`
- `gateway_file_assets`
- `gateway_nonces`
- `gateway_plugins`

## Deployment Notes

- `Procfile` and `render.yaml` support Gunicorn + Uvicorn.
- `vercel.json` continues to support ASGI deployment.
- Redis is optional and automatically used when `REDIS_URL` is set.
- On Linux and serverless targets, upload storage defaults to `/tmp/data/gateway_uploads`.

## Environment Variables

- `GATEWAY_SECRET_KEY`
- `GATEWAY_REQUEST_SIGNING_SECRET`
- `GATEWAY_ALLOWED_ORIGINS`
- `GATEWAY_ALLOWED_IPS`
- `GATEWAY_CORS_ALLOW_CREDENTIALS`
- `REDIS_URL`
- `AI_PROVIDER_TIMEOUT_SECONDS`
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`
- `GEMINI_API_KEY`, `GEMINI_BASE_URL`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`
- `XAI_API_KEY`, `XAI_BASE_URL`
- `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`
- `OLLAMA_BASE_URL`
- `CUSTOM_OPENAI_API_KEY`, `CUSTOM_OPENAI_BASE_URL`

## OpenAPI and Swagger

- Interactive Swagger UI is available at `/docs`.
- ReDoc is available at `/redoc`.
- The generated OpenAPI document is available at `/openapi.json`.
- Run `py generate_openapi.py` to export a static copy to `openapi/ai_gateway_openapi.json`.
