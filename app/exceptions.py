from typing import Any, Optional

class AppError(Exception):
    """Base application error for controlled re-raises."""

    def __init__(self, message: str, *, code: Optional[str] = None, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


class ExternalDependencyError(AppError):
    """Errors from external services (HTTP, Redis, etc.)"""


class IntegrationError(AppError):
    """Errors during data integration or parsing."""


class DatabaseError(AppError):
    """Database related errors."""
