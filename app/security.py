from fastapi import HTTPException, status
from app.config import get_settings


def verify_webhook_token(token: str | None) -> None:
    expected = get_settings().webhook_secret
    if not expected:
        return
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook token",
        )
