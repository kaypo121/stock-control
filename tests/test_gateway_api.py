from io import BytesIO


def _create_admin_principal(client):
    response = client.post(
        "/v1/auth/principals",
        json={
            "name": "Gateway Admin",
            "principal_type": "ADMIN",
            "role": "ADMIN",
            "organizationId": "org-1",
            "workspaceId": "workspace-1",
            "projectId": "project-1",
        },
    )
    assert response.status_code == 201
    payload = response.json()["data"]
    return payload["principal"], payload["clientSecret"]


def _issue_token(client):
    principal, client_secret = _create_admin_principal(client)
    response = client.post(
        "/v1/auth/token",
        json={
            "principalId": principal["principalId"],
            "clientSecret": client_secret,
            "grantType": "client_credentials",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_gateway_provider_catalog_requires_auth_and_returns_registry(client):
    headers = _issue_token(client)
    response = client.get("/v1/ai/providers", headers=headers)

    assert response.status_code == 200
    assert response.json()["success"] is True
    providers = response.json()["data"]["providers"]
    assert any(provider["canonicalName"] == "openai" for provider in providers)
    assert any(provider["canonicalName"] == "ollama" for provider in providers)


def test_gateway_duplicate_request_returns_cached_response(client):
    headers = _issue_token(client)
    payload = {
        "requestId": "duplicate-request-1",
        "context": {
            "sessionId": "session-1",
            "traceId": "trace-1",
            "correlationId": "corr-1",
        },
        "action": {
            "module": "gateway",
            "resource": "context",
            "operation": "echo",
            "mode": "sync",
        },
        "payload": {"hello": "world"},
        "metadata": {"source": "test"},
    }

    first = client.post("/v1/ai/execute", json=payload, headers=headers)
    second = client.post("/v1/ai/execute", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["duplicate"] is True


def test_gateway_chat_completion_uses_provider_service(client, monkeypatch):
    headers = _issue_token(client)

    async def fake_completion(payload, request_id, trace_id):
        return {
            "provider": "openai",
            "model": payload.model,
            "id": "cmpl-test",
            "object": "chat.completion",
            "created": 1234567890,
            "message": {"role": "assistant", "content": "Gateway response"},
            "choices": [{"message": {"role": "assistant", "content": "Gateway response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "finishReason": "stop",
        }

    monkeypatch.setattr(
        "app.api.gateway_endpoints.provider_service.require_provider",
        lambda provider_name: {"canonicalName": "openai", "configured": True},
    )
    monkeypatch.setattr("app.api.gateway_endpoints.provider_service.chat_completion", fake_completion)

    response = client.post(
        "/v1/chat/completions",
        json={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello gateway"}],
            "stream": False,
            "context": {"traceId": "trace-chat-1", "correlationId": "corr-chat-1"},
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["provider"] == "openai"
    assert response.json()["data"]["message"]["content"] == "Gateway response"


def test_gateway_upload_rejects_unsupported_extension(client):
    headers = _issue_token(client)
    response = client.post(
        "/v1/files/upload",
        headers=headers,
        files={"file": ("malware.exe", BytesIO(b"payload"), "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "UNSUPPORTED_FILE"
