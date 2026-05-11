"""HTTP-исключения auth-модуля.

Наследуются от fastapi.HTTPException — автоматически конвертируются в
HTTP-ответы с правильными кодами и Problem Details payload.
"""

from fastapi import HTTPException, status


class UnauthorizedError(HTTPException):
    """HTTP 401 — нет валидного токена."""

    def __init__(self, detail: str = "Unauthorized") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidTokenError(UnauthorizedError):
    """HTTP 401 — токен не прошёл валидацию (signature/expiry/audience/algorithm)."""

    def __init__(self, detail: str = "Invalid token") -> None:
        super().__init__(detail=detail)


class ForbiddenError(HTTPException):
    """HTTP 403 — токен валиден, но access_level не позволяет."""

    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
