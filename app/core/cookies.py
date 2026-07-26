from fastapi import Response

from app.core.config import settings


def _cookie_kwargs() -> dict:
    kwargs = dict(
        path="/",
        httponly=settings.COOKIE_HTTPONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
    if settings.COOKIE_DOMAIN:  # bo'sh string yoki None bo'lsa qo'shilmaydi
        kwargs["domain"] = settings.COOKIE_DOMAIN
    return kwargs


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=60 * settings.ACCESS_TOKEN_MINUTES,
        **_cookie_kwargs(),
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=60 * 60 * 24 * settings.REFRESH_TOKEN_DAYS,
        **_cookie_kwargs(),
    )


def clear_auth_cookies(response: Response) -> None:
    kwargs = _cookie_kwargs()
    kwargs.pop("httponly", None)
    kwargs.pop("secure", None)
    kwargs.pop("samesite", None)
    response.delete_cookie(key="access_token", **kwargs)
    response.delete_cookie(key="refresh_token", **kwargs)
