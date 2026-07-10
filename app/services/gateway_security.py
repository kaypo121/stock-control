import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import (
    GATEWAY_API_KEY_EXPIRY_DAYS,
    GATEWAY_BURST_LIMIT,
    GATEWAY_JWT_ALGORITHM,
    GATEWAY_JWT_EXPIRES_MINUTES,
    GATEWAY_REQUEST_BODY_LIMIT_BYTES,
    GATEWAY_REQUEST_SIGNING_SECRET,
    GATEWAY_SECRET_KEY,
    GATEWAY_RATE_LIMIT_DAY,
    GATEWAY_RATE_LIMIT_HOUR,
    GATEWAY_RATE_LIMIT_MINUTE,
)
from app.models.gateway_models import (
    GatewayApiKey,
    GatewayAuditLog,
    GatewayNonce,
    GatewayPrincipal,
    GatewayRateLimitBucket,
)
from app.schemas.gateway_schemas import ApiKeyCreateRequest, PrincipalRegistrationRequest, TokenRequest


ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "ADMIN": ["*"],
    "MANAGER": [
        "gateway:read",
        "gateway:write",
        "events:publish",
        "webhooks:manage",
        "files:manage",
        "tasks:manage",
        "stock:read",
        "stock:write",
        "quality:read",
        "quality:write",
        "integration:read",
        "integration:write",
    ],
    "EMPLOYEE": [
        "gateway:read",
        "files:read",
        "tasks:read",
        "stock:read",
        "quality:read",
        "integration:read",
    ],
    "AI_AGENT": [
        "gateway:read",
        "gateway:write",
        "events:publish",
        "files:read",
        "files:write",
        "tasks:manage",
        "stock:read",
        "quality:read",
        "integration:read",
        "tools:execute",
    ],
    "AUTOMATION_SERVICE": [
        "gateway:read",
        "gateway:write",
        "events:publish",
        "tasks:manage",
        "webhooks:manage",
        "stock:read",
        "quality:read",
        "integration:read",
    ],
    "THIRD_PARTY": ["gateway:read", "gateway:write", "events:publish", "files:read", "stock:read"],
    "READ_ONLY": ["gateway:read", "files:read", "stock:read", "quality:read", "integration:read", "tasks:read"],
}


class GatewayAPIError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, detail: Optional[Any] = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "detail": detail})


def utcnow() -> datetime:
    return datetime.utcnow()


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _encode_hash(salt: bytes, digest: bytes) -> str:
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 120_000)
    return _encode_hash(salt, digest)


def verify_secret(secret: str, stored_hash: str) -> bool:
    try:
        salt_b64, digest_b64 = stored_hash.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        digest = base64.urlsafe_b64decode(digest_b64.encode())
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(computed, digest)


def generate_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def serialize_permissions(role: str, custom_permissions: List[str]) -> str:
    if custom_permissions:
        permissions = sorted(set(custom_permissions))
    else:
        permissions = ROLE_PERMISSIONS.get(role.upper(), ["gateway:read"])
    return json.dumps(permissions)


def build_permission_list(principal: GatewayPrincipal, scopes: Optional[List[str]] = None) -> List[str]:
    permissions = set(_json_loads(principal.permissions_json, []))
    if scopes:
        permissions.update(scopes)
    return sorted(permissions)


class GatewaySecurityService:
    def create_principal(self, db: Session, payload: PrincipalRegistrationRequest) -> Tuple[GatewayPrincipal, str]:
        secret = payload.secret or generate_secret("agw_client")
        principal = GatewayPrincipal(
            name=payload.name,
            principal_type=payload.principal_type,
            role=payload.role.upper(),
            organization_id=payload.organization_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            hashed_secret=hash_secret(secret),
            permissions_json=serialize_permissions(payload.role, payload.permissions),
            metadata_json=json.dumps(payload.metadata),
            is_active=True,
        )
        db.add(principal)
        db.commit()
        db.refresh(principal)
        self._audit(db, principal.id, "AUTH", "principal.create", principal.principal_id, "SUCCESS", {})
        return principal, secret

    def create_api_key(self, db: Session, payload: ApiKeyCreateRequest) -> Tuple[GatewayApiKey, str, GatewayPrincipal]:
        principal = db.query(GatewayPrincipal).filter(GatewayPrincipal.principal_id == payload.principal_id).first()
        if not principal or not principal.is_active:
            raise GatewayAPIError(status.HTTP_404_NOT_FOUND, "PRINCIPAL_NOT_FOUND", "Principal was not found or is inactive.")

        plain_secret = generate_secret("agw_key")
        api_key = GatewayApiKey(
            principal_id=principal.id,
            label=payload.label,
            credential_type=payload.credential_type,
            key_prefix=plain_secret[:16],
            hashed_key=hash_secret(plain_secret),
            scopes_json=json.dumps(payload.scopes),
            metadata_json=json.dumps(payload.metadata),
            expires_at=utcnow() + timedelta(days=payload.expires_in_days or GATEWAY_API_KEY_EXPIRY_DAYS),
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        self._audit(db, principal.id, "AUTH", "apikey.create", api_key.key_id, "SUCCESS", {"label": payload.label})
        return api_key, plain_secret, principal

    def rotate_api_key(self, db: Session, key_id: str) -> Tuple[GatewayApiKey, GatewayApiKey, str]:
        existing = db.query(GatewayApiKey).filter(GatewayApiKey.key_id == key_id, GatewayApiKey.is_active.is_(True)).first()
        if not existing:
            raise GatewayAPIError(status.HTTP_404_NOT_FOUND, "API_KEY_NOT_FOUND", "API key was not found.")

        existing.is_active = False
        plain_secret = generate_secret("agw_key")
        replacement = GatewayApiKey(
            principal_id=existing.principal_id,
            label=f"{existing.label}-rotated",
            credential_type=existing.credential_type,
            key_prefix=plain_secret[:16],
            hashed_key=hash_secret(plain_secret),
            scopes_json=existing.scopes_json,
            metadata_json=existing.metadata_json,
            expires_at=utcnow() + timedelta(days=GATEWAY_API_KEY_EXPIRY_DAYS),
            rotated_from_key_id=existing.key_id,
        )
        db.add(replacement)
        db.commit()
        db.refresh(replacement)
        return existing, replacement, plain_secret

    def issue_token(self, db: Session, payload: TokenRequest) -> Dict[str, Any]:
        principal = db.query(GatewayPrincipal).filter(GatewayPrincipal.principal_id == payload.principal_id).first()
        if not principal or not principal.is_active:
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_CLIENT", "Invalid principal credentials.")
        if not principal.hashed_secret or not verify_secret(payload.client_secret, principal.hashed_secret):
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_CLIENT", "Invalid principal credentials.")

        permissions = build_permission_list(principal, payload.scopes)
        issued_at = utcnow()
        expires_at = issued_at + timedelta(minutes=GATEWAY_JWT_EXPIRES_MINUTES)
        token_payload = {
            "sub": principal.principal_id,
            "role": principal.role,
            "principal_type": principal.principal_type,
            "permissions": permissions,
            "organization_id": principal.organization_id,
            "workspace_id": principal.workspace_id,
            "project_id": principal.project_id,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(uuid.uuid4()),
            "grant_type": payload.grant_type,
        }
        encoded = jwt.encode(token_payload, GATEWAY_SECRET_KEY, algorithm=GATEWAY_JWT_ALGORITHM)
        principal.last_authenticated_at = issued_at
        db.commit()
        self._audit(db, principal.id, "AUTH", "token.issue", principal.principal_id, "SUCCESS", {"grant_type": payload.grant_type})
        return {
            "accessToken": encoded,
            "tokenType": "bearer",
            "expiresIn": GATEWAY_JWT_EXPIRES_MINUTES * 60,
            "scope": " ".join(permissions),
            "principalId": principal.principal_id,
            "role": principal.role,
        }

    def authenticate_request(self, db: Session, request: Request) -> Optional[Dict[str, Any]]:
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key")
        service_token = request.headers.get("X-Service-Token")
        machine_token = request.headers.get("X-Machine-Token")

        if auth_header.startswith("Bearer "):
            bearer_token = auth_header.split(" ", 1)[1].strip()
            try:
                payload = jwt.decode(
                    bearer_token,
                    GATEWAY_SECRET_KEY,
                    algorithms=[GATEWAY_JWT_ALGORITHM],
                    leeway=30,
                    options={"verify_iat": False},
                )
            except jwt.InvalidTokenError as exc:
                raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Bearer token is invalid or expired.", str(exc))

            principal = db.query(GatewayPrincipal).filter(GatewayPrincipal.principal_id == payload["sub"]).first()
            if not principal or not principal.is_active:
                raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Token principal is inactive.")

            identity = {
                "principal": principal,
                "permissions": payload.get("permissions", []),
                "role": payload.get("role"),
                "credential_type": "JWT",
                "scopes": payload.get("permissions", []),
            }
            principal.last_authenticated_at = utcnow()
            db.commit()
            return identity

        raw_secret = api_key_header or service_token or machine_token
        if raw_secret:
            credential_type = "API_KEY"
            if service_token:
                credential_type = "SERVICE_TOKEN"
            if machine_token:
                credential_type = "MACHINE_TOKEN"

            key_prefix = raw_secret[:16]
            candidates = (
                db.query(GatewayApiKey)
                .filter(
                    GatewayApiKey.key_prefix == key_prefix,
                    GatewayApiKey.is_active.is_(True),
                    GatewayApiKey.credential_type == credential_type,
                )
                .all()
            )
            for candidate in candidates:
                if candidate.expires_at and candidate.expires_at < utcnow():
                    continue
                if verify_secret(raw_secret, candidate.hashed_key):
                    principal = db.query(GatewayPrincipal).filter(GatewayPrincipal.id == candidate.principal_id).first()
                    if not principal or not principal.is_active:
                        raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIAL", "Associated principal is inactive.")
                    candidate.last_used_at = utcnow()
                    principal.last_authenticated_at = utcnow()
                    db.commit()
                    return {
                        "principal": principal,
                        "permissions": build_permission_list(principal, _json_loads(candidate.scopes_json, [])),
                        "role": principal.role,
                        "credential_type": credential_type,
                        "scopes": _json_loads(candidate.scopes_json, []),
                    }
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIAL", "API credential is invalid or expired.")

        return None

    def require_permissions(self, identity: Optional[Dict[str, Any]], required_permissions: List[str]) -> None:
        if not required_permissions:
            return
        if not identity:
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "Authentication is required for this endpoint.")
        permissions = set(identity.get("permissions", []))
        if "*" in permissions:
            return
        missing = [permission for permission in required_permissions if permission not in permissions]
        if missing:
            raise GatewayAPIError(
                status.HTTP_403_FORBIDDEN,
                "PERMISSION_DENIED",
                "The authenticated principal does not have the required permissions.",
                {"missingPermissions": missing},
            )

    async def validate_request_body(self, request: Request) -> bytes:
        body = await request.body()
        if len(body) > GATEWAY_REQUEST_BODY_LIMIT_BYTES:
            raise GatewayAPIError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "REQUEST_TOO_LARGE",
                "Request body exceeds the configured gateway size limit.",
                {"maxBytes": GATEWAY_REQUEST_BODY_LIMIT_BYTES},
            )
        return body

    def validate_request_signature(
        self,
        db: Session,
        identity: Optional[Dict[str, Any]],
        body: bytes,
        request: Request,
    ) -> None:
        signature = request.headers.get("X-Signature")
        nonce = request.headers.get("X-Nonce")
        timestamp = request.headers.get("X-Timestamp")
        if not any([signature, nonce, timestamp]):
            return
        if not all([signature, nonce, timestamp]):
            raise GatewayAPIError(status.HTTP_400_BAD_REQUEST, "INVALID_SIGNATURE", "Signature headers are incomplete.")
        try:
            timestamp_value = int(timestamp)
        except ValueError as exc:
            raise GatewayAPIError(status.HTTP_400_BAD_REQUEST, "INVALID_SIGNATURE", "Timestamp must be a UNIX epoch integer.", str(exc))
        if abs(int(datetime.utcnow().timestamp()) - timestamp_value) > 300:
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "SIGNATURE_EXPIRED", "Signed request timestamp is outside the accepted window.")
        if not identity:
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "Signed requests still require authentication.")

        signing_input = f"{timestamp}.{nonce}.".encode("utf-8") + body
        expected = hmac.new(
            GATEWAY_REQUEST_SIGNING_SECRET.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise GatewayAPIError(status.HTTP_401_UNAUTHORIZED, "INVALID_SIGNATURE", "Request signature verification failed.")

        principal = identity["principal"]
        existing = db.query(GatewayNonce).filter(GatewayNonce.nonce == nonce).first()
        if existing:
            raise GatewayAPIError(status.HTTP_409_CONFLICT, "REPLAY_ATTACK_DETECTED", "The request nonce has already been used.")
        db.add(
            GatewayNonce(
                nonce=nonce,
                principal_id=principal.id,
                request_signature=signature,
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        db.commit()

    def apply_rate_limit(self, db: Session, request: Request, identity: Optional[Dict[str, Any]]) -> None:
        principal = identity["principal"] if identity else None
        org_id = principal.organization_id if principal else request.headers.get("X-Organization-Id", "anonymous")
        identifier = principal.principal_id if principal else request.client.host if request.client else "anonymous"
        checks = [
            ("burst", GATEWAY_BURST_LIMIT, utcnow().replace(microsecond=0, second=(utcnow().second // 5) * 5)),
            ("minute", GATEWAY_RATE_LIMIT_MINUTE, utcnow().replace(second=0, microsecond=0)),
            ("hour", GATEWAY_RATE_LIMIT_HOUR, utcnow().replace(minute=0, second=0, microsecond=0)),
            ("day", GATEWAY_RATE_LIMIT_DAY, utcnow().replace(hour=0, minute=0, second=0, microsecond=0)),
        ]
        scopes = {
            "user": identifier,
            "organization": org_id or "anonymous",
        }
        for window_name, limit_value, window_started_at in checks:
            for scope, scope_identifier in scopes.items():
                bucket_key = f"{scope}:{scope_identifier}:{window_name}"
                bucket = db.query(GatewayRateLimitBucket).filter(GatewayRateLimitBucket.bucket_key == bucket_key).first()
                if not bucket:
                    bucket = GatewayRateLimitBucket(
                        bucket_key=bucket_key,
                        scope=scope,
                        identifier=scope_identifier,
                        window_name=window_name,
                        window_started_at=window_started_at,
                        request_count=0,
                    )
                    db.add(bucket)
                elif bucket.window_started_at != window_started_at:
                    bucket.window_started_at = window_started_at
                    bucket.request_count = 0
                bucket.request_count += 1
                if bucket.request_count > limit_value:
                    db.commit()
                    raise GatewayAPIError(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "RATE_LIMIT_EXCEEDED",
                        "Gateway rate limit exceeded.",
                        {"scope": scope, "window": window_name, "limit": limit_value},
                    )
        db.commit()

    def _audit(
        self,
        db: Session,
        principal_db_id: Optional[int],
        event_type: str,
        action: str,
        resource: str,
        result: str,
        details: Dict[str, Any],
    ) -> None:
        db.add(
            GatewayAuditLog(
                principal_id=principal_db_id,
                event_type=event_type,
                action=action,
                resource=resource,
                result=result,
                details_json=json.dumps(details),
            )
        )
        db.commit()
