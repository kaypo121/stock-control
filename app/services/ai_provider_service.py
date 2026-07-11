import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import status

from app.config import AI_PROVIDER_TIMEOUT_SECONDS
from app.schemas.gateway_schemas import ChatCompletionRequest
from app.services.gateway_security import GatewayAPIError


@dataclass(frozen=True)
class ProviderDefinition:
    canonical_name: str
    display_name: str
    family: str
    default_base_url: str
    env_api_key: Optional[str]
    env_base_url: Optional[str]
    stream_support: bool = True
    requires_api_key: bool = True
    default_models: tuple[str, ...] = ()


PROVIDER_ALIASES: Dict[str, str] = {
    "chatgpt": "openai",
    "openai": "openai",
    "claude": "anthropic",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "grok": "grok",
    "xai": "grok",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "local-llm": "ollama",
    "local_llm": "ollama",
    "local": "ollama",
    "custom": "custom_openai",
    "custom_openai": "custom_openai",
}


PROVIDER_DEFINITIONS: Dict[str, ProviderDefinition] = {
    "openai": ProviderDefinition(
        canonical_name="openai",
        display_name="OpenAI / ChatGPT",
        family="openai_compatible",
        default_base_url="https://api.openai.com/v1",
        env_api_key="OPENAI_API_KEY",
        env_base_url="OPENAI_BASE_URL",
        default_models=("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"),
    ),
    "anthropic": ProviderDefinition(
        canonical_name="anthropic",
        display_name="Anthropic / Claude",
        family="anthropic",
        default_base_url="https://api.anthropic.com/v1",
        env_api_key="ANTHROPIC_API_KEY",
        env_base_url="ANTHROPIC_BASE_URL",
        stream_support=False,
        default_models=("claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"),
    ),
    "gemini": ProviderDefinition(
        canonical_name="gemini",
        display_name="Google Gemini",
        family="gemini",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        env_api_key="GEMINI_API_KEY",
        env_base_url="GEMINI_BASE_URL",
        stream_support=False,
        default_models=("gemini-1.5-flash", "gemini-1.5-pro"),
    ),
    "deepseek": ProviderDefinition(
        canonical_name="deepseek",
        display_name="DeepSeek",
        family="openai_compatible",
        default_base_url="https://api.deepseek.com/v1",
        env_api_key="DEEPSEEK_API_KEY",
        env_base_url="DEEPSEEK_BASE_URL",
        default_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    "grok": ProviderDefinition(
        canonical_name="grok",
        display_name="xAI / Grok",
        family="openai_compatible",
        default_base_url="https://api.x.ai/v1",
        env_api_key="XAI_API_KEY",
        env_base_url="XAI_BASE_URL",
        default_models=("grok-beta",),
    ),
    "openrouter": ProviderDefinition(
        canonical_name="openrouter",
        display_name="OpenRouter",
        family="openai_compatible",
        default_base_url="https://openrouter.ai/api/v1",
        env_api_key="OPENROUTER_API_KEY",
        env_base_url="OPENROUTER_BASE_URL",
        default_models=("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"),
    ),
    "ollama": ProviderDefinition(
        canonical_name="ollama",
        display_name="Ollama",
        family="ollama",
        default_base_url="http://localhost:11434",
        env_api_key=None,
        env_base_url="OLLAMA_BASE_URL",
        requires_api_key=False,
        default_models=("llama3.1", "qwen2.5", "mistral"),
    ),
    "custom_openai": ProviderDefinition(
        canonical_name="custom_openai",
        display_name="Custom OpenAI-Compatible",
        family="openai_compatible",
        default_base_url="http://localhost:8001/v1",
        env_api_key="CUSTOM_OPENAI_API_KEY",
        env_base_url="CUSTOM_OPENAI_BASE_URL",
        requires_api_key=False,
        default_models=("custom-model",),
    ),
}


def _safe_json_loads(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _message_payload(messages: List[Any]) -> List[Dict[str, Any]]:
    return [message.model_dump(exclude_none=True) for message in messages]


class AIProviderService:
    def canonical_provider(self, provider_name: str) -> str:
        canonical = PROVIDER_ALIASES.get(provider_name.strip().lower())
        if canonical:
            return canonical
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "PROVIDER_NOT_FOUND",
            "The requested AI provider is not supported by the gateway.",
            {
                "provider": provider_name,
                "supportedProviders": sorted(PROVIDER_DEFINITIONS),
            },
        )

    def resolve_provider(self, provider_name: str) -> Dict[str, Any]:
        canonical = self.canonical_provider(provider_name)
        definition = PROVIDER_DEFINITIONS[canonical]
        api_key = (
            os.getenv(definition.env_api_key, "") if definition.env_api_key else ""
        )
        base_url = os.getenv(
            definition.env_base_url, definition.default_base_url
        ).rstrip("/")
        configured = bool(base_url) and (
            bool(api_key) if definition.requires_api_key else True
        )
        return {
            "canonicalName": canonical,
            "displayName": definition.display_name,
            "family": definition.family,
            "baseUrl": base_url,
            "apiKey": api_key,
            "requiresApiKey": definition.requires_api_key,
            "configured": configured,
            "streamSupport": definition.stream_support,
            "defaultModels": list(definition.default_models),
        }

    def require_provider(self, provider_name: str) -> Dict[str, Any]:
        provider = self.resolve_provider(provider_name)
        if not provider["configured"]:
            raise GatewayAPIError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "PROVIDER_NOT_CONFIGURED",
                "The requested AI provider is not configured for this gateway environment.",
                {
                    "provider": provider["canonicalName"],
                    "baseUrl": provider["baseUrl"],
                    "requiresApiKey": provider["requiresApiKey"],
                },
            )
        return provider

    def catalog(self) -> List[Dict[str, Any]]:
        return [self.resolve_provider(name) for name in PROVIDER_DEFINITIONS]

    def model_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "provider": provider["canonicalName"],
                "configured": provider["configured"],
                "models": provider["defaultModels"],
            }
            for provider in self.catalog()
        ]

    async def chat_completion(
        self, payload: ChatCompletionRequest, request_id: str, trace_id: str
    ) -> Dict[str, Any]:
        provider = self.require_provider(payload.provider)
        if provider["family"] == "openai_compatible":
            return await self._openai_compatible_completion(
                provider, payload, request_id, trace_id
            )
        if provider["family"] == "anthropic":
            return await self._anthropic_completion(
                provider, payload, request_id, trace_id
            )
        if provider["family"] == "gemini":
            return await self._gemini_completion(
                provider, payload, request_id, trace_id
            )
        if provider["family"] == "ollama":
            return await self._ollama_completion(
                provider, payload, request_id, trace_id
            )
        raise GatewayAPIError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PROVIDER_FAMILY_UNSUPPORTED",
            "Unsupported provider family.",
        )

    async def stream_chat_completion(
        self, payload: ChatCompletionRequest, request_id: str, trace_id: str
    ) -> AsyncIterator[str]:
        provider = self.require_provider(payload.provider)
        if provider["family"] == "openai_compatible" and provider["streamSupport"]:
            async for chunk in self._stream_openai_compatible(
                provider, payload, request_id, trace_id
            ):
                yield chunk
            return
        if provider["family"] == "ollama" and provider["streamSupport"]:
            async for chunk in self._stream_ollama(
                provider, payload, request_id, trace_id
            ):
                yield chunk
            return

        # Fall back to chunked gateway streaming when the upstream provider does not
        # expose a compatible stream API through this lightweight adapter.
        response = await self.chat_completion(payload, request_id, trace_id)
        content = response.get("message", {}).get("content", "")
        chunk_size = max(32, len(content) // 4 or 32)
        for start in range(0, len(content), chunk_size):
            piece = content[start : start + chunk_size]
            body = {
                "provider": response["provider"],
                "model": response["model"],
                "delta": piece,
                "done": False,
                "requestId": request_id,
                "traceId": trace_id,
            }
            yield f"data: {json.dumps(body)}\n\n"
        yield f"data: {json.dumps({'provider': response['provider'], 'model': response['model'], 'done': True, 'requestId': request_id, 'traceId': trace_id})}\n\n"
        yield "event: complete\ndata: [DONE]\n\n"

    async def _openai_compatible_completion(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        body = {
            "model": payload.model,
            "messages": _message_payload(payload.messages),
            "stream": False,
        }
        body.update(self._provider_options(payload))
        response_json = await self._post_json(
            url=f"{provider['baseUrl']}/chat/completions",
            headers=self._default_headers(provider, request_id, trace_id),
            json_body=body,
        )
        choice = (response_json.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {
            "provider": provider["canonicalName"],
            "model": response_json.get("model", payload.model),
            "id": response_json.get("id"),
            "object": response_json.get("object", "chat.completion"),
            "created": response_json.get("created"),
            "message": {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
            },
            "choices": response_json.get("choices", []),
            "usage": response_json.get("usage", {}),
            "finishReason": choice.get("finish_reason"),
        }

    async def _anthropic_completion(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        system_messages = [
            message.content for message in payload.messages if message.role == "system"
        ]
        messages = [
            {
                "role": "assistant" if message.role == "assistant" else "user",
                "content": [{"type": "text", "text": message.content}],
            }
            for message in payload.messages
            if message.role != "system"
        ]
        body = {
            "model": payload.model,
            "messages": messages,
            "max_tokens": int(payload.metadata.get("maxTokens", 1024)),
        }
        if system_messages:
            body["system"] = "\n".join(system_messages)
        body.update(self._provider_options(payload))
        headers = self._default_headers(provider, request_id, trace_id)
        headers["x-api-key"] = provider["apiKey"]
        headers["anthropic-version"] = payload.metadata.get(
            "anthropicVersion", "2023-06-01"
        )
        headers.pop("Authorization", None)
        response_json = await self._post_json(
            url=f"{provider['baseUrl']}/messages",
            headers=headers,
            json_body=body,
        )
        content_blocks = response_json.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        )
        return {
            "provider": provider["canonicalName"],
            "model": response_json.get("model", payload.model),
            "id": response_json.get("id"),
            "object": response_json.get("type", "message"),
            "created": response_json.get("created_at"),
            "message": {"role": "assistant", "content": text},
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": response_json.get("stop_reason"),
                }
            ],
            "usage": response_json.get("usage", {}),
            "finishReason": response_json.get("stop_reason"),
        }

    async def _gemini_completion(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        contents = []
        system_text = "\n".join(
            message.content for message in payload.messages if message.role == "system"
        )
        for message in payload.messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        body: Dict[str, Any] = {"contents": contents}
        if system_text:
            body["system_instruction"] = {"parts": [{"text": system_text}]}
        generation_config = payload.metadata.get("generationConfig", {})
        if generation_config:
            body["generationConfig"] = generation_config
        response_json = await self._post_json(
            url=f"{provider['baseUrl']}/{payload.model}:generateContent?key={provider['apiKey']}",
            headers=self._default_headers(
                provider, request_id, trace_id, include_auth=False
            ),
            json_body=body,
        )
        candidates = response_json.get("candidates") or [{}]
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)
        usage = response_json.get("usageMetadata", {})
        return {
            "provider": provider["canonicalName"],
            "model": payload.model,
            "id": response_json.get("responseId"),
            "object": "generateContentResponse",
            "created": None,
            "message": {"role": "assistant", "content": text},
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": candidates[0].get("finishReason"),
                }
            ],
            "usage": {
                "promptTokenCount": usage.get("promptTokenCount"),
                "candidatesTokenCount": usage.get("candidatesTokenCount"),
                "totalTokenCount": usage.get("totalTokenCount"),
            },
            "finishReason": candidates[0].get("finishReason"),
        }

    async def _ollama_completion(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        body = {
            "model": payload.model,
            "messages": _message_payload(payload.messages),
            "stream": False,
        }
        body.update(self._provider_options(payload))
        response_json = await self._post_json(
            url=f"{provider['baseUrl']}/api/chat",
            headers=self._default_headers(
                provider, request_id, trace_id, include_auth=False
            ),
            json_body=body,
        )
        message = response_json.get("message") or {}
        return {
            "provider": provider["canonicalName"],
            "model": response_json.get("model", payload.model),
            "id": response_json.get("created_at"),
            "object": "chat.completion",
            "created": response_json.get("created_at"),
            "message": {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
            },
            "choices": [
                {
                    "message": message,
                    "finish_reason": ("stop" if response_json.get("done") else None),
                }
            ],
            "usage": response_json.get("usage", {}),
            "finishReason": "stop" if response_json.get("done") else None,
        }

    async def _stream_openai_compatible(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> AsyncIterator[str]:
        body = {
            "model": payload.model,
            "messages": _message_payload(payload.messages),
            "stream": True,
        }
        body.update(self._provider_options(payload))
        headers = self._default_headers(provider, request_id, trace_id)
        async with httpx.AsyncClient(timeout=AI_PROVIDER_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                f"{provider['baseUrl']}/chat/completions",
                headers=headers,
                json=body,
            ) as response:
                await self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    item = _safe_json_loads(raw)
                    choice = (item.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    body_chunk = {
                        "provider": provider["canonicalName"],
                        "model": item.get("model", payload.model),
                        "delta": delta.get("content", ""),
                        "role": delta.get("role"),
                        "finishReason": choice.get("finish_reason"),
                        "requestId": request_id,
                        "traceId": trace_id,
                        "done": False,
                    }
                    yield f"data: {json.dumps(body_chunk)}\n\n"
        yield f"data: {json.dumps({'provider': provider['canonicalName'], 'model': payload.model, 'done': True, 'requestId': request_id, 'traceId': trace_id})}\n\n"
        yield "event: complete\ndata: [DONE]\n\n"

    async def _stream_ollama(
        self,
        provider: Dict[str, Any],
        payload: ChatCompletionRequest,
        request_id: str,
        trace_id: str,
    ) -> AsyncIterator[str]:
        body = {
            "model": payload.model,
            "messages": _message_payload(payload.messages),
            "stream": True,
        }
        body.update(self._provider_options(payload))
        headers = self._default_headers(
            provider, request_id, trace_id, include_auth=False
        )
        async with httpx.AsyncClient(timeout=AI_PROVIDER_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                f"{provider['baseUrl']}/api/chat",
                headers=headers,
                json=body,
            ) as response:
                await self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    item = _safe_json_loads(line)
                    message = item.get("message") or {}
                    body_chunk = {
                        "provider": provider["canonicalName"],
                        "model": item.get("model", payload.model),
                        "delta": message.get("content", ""),
                        "role": message.get("role"),
                        "requestId": request_id,
                        "traceId": trace_id,
                        "done": bool(item.get("done")),
                    }
                    yield f"data: {json.dumps(body_chunk)}\n\n"
        yield "event: complete\ndata: [DONE]\n\n"

    async def _post_json(
        self, url: str, headers: Dict[str, str], json_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=AI_PROVIDER_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=json_body)
        if response.status_code >= 400:
            self._raise_error_response(response)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise GatewayAPIError(
                status.HTTP_502_BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "The upstream AI provider returned a non-JSON response.",
                {"url": url, "detail": str(exc), "body": response.text[:1000]},
            )

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        body = await response.aread()
        text = body.decode("utf-8", errors="ignore")
        self._raise_error_response(response, response_text=text)

    def _raise_error_response(
        self, response: httpx.Response, response_text: Optional[str] = None
    ) -> None:
        text = response_text if response_text is not None else response.text
        detail: Any
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = {"body": text[:1000]}
        raise GatewayAPIError(
            status.HTTP_502_BAD_GATEWAY,
            "UPSTREAM_PROVIDER_ERROR",
            "The upstream AI provider request failed.",
            {
                "statusCode": response.status_code,
                "url": str(response.request.url) if response.request else None,
                "detail": detail,
            },
        )

    def _default_headers(
        self,
        provider: Dict[str, Any],
        request_id: str,
        trace_id: str,
        include_auth: bool = True,
    ) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-Id": request_id,
            "X-Trace-Id": trace_id,
            "User-Agent": "agriculture-ai-gateway/1.0",
        }
        if include_auth and provider.get("apiKey"):
            headers["Authorization"] = f"Bearer {provider['apiKey']}"
        return headers

    def _provider_options(self, payload: ChatCompletionRequest) -> Dict[str, Any]:
        options = payload.metadata.get("providerOptions", {})
        return options if isinstance(options, dict) else {}


provider_service = AIProviderService()
