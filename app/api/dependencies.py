from typing import Any, Dict

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.gateway_security import GatewayAPIError, GatewaySecurityService

security_service = GatewaySecurityService()


def require_permissions(*permissions: str):
    required = [permission for permission in permissions if permission]

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        identity = security_service.authenticate_request(db, request)
        if identity is None:
            raise GatewayAPIError(
                status.HTTP_401_UNAUTHORIZED,
                "AUTH_REQUIRED",
                "Authentication is required for this endpoint.",
            )
        security_service.require_permissions(identity, required)
        request.state.gateway_identity = identity
        return identity

    return dependency

