"""Social-login building blocks: Telegram (OIDC id_token, legacy widget, Mini App)
and Google (id_token / access_token).

Hech qanday FastAPI/SQLAlchemy'ga bog'liq emas — faqat "tashqi tokenni tekshir
va bir xil ko'rinishdagi `SocialProfile` qaytar" vazifasini bajaradi. Shu sabab
alohida test qilish oson. Baza bilan ishlash (topish / bog'lash / yaratish)
`AuthService` ichida qoladi.

Xatolar `SocialAuthError` sifatida ko'tariladi, `AuthService` ularni
`HTTPException`ga aylantiradi.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

import httpx
import jwt as pyjwt

logger = logging.getLogger(__name__)


class SocialAuthError(Exception):
    """Provider token/payload yaroqsiz yoki provider bilan aloqa muvaffaqiyatsiz."""

    def __init__(self, detail: str, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(slots=True)
class SocialProfile:
    """Provider'dan olingan, bir xil ko'rinishga keltirilgan profil."""

    provider: str  # "google" | "telegram"
    provider_id: str
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    username_hint: str | None = None  # Telegram @username (bo'lsa)
    email: str | None = None
    email_verified: bool = False
    avatar: str | None = None
    phone: str | None = None  # faqat raqamlar: 998901234567
    phone_verified: bool = False
    locale: str | None = None


# ──────────────────────────────────────────────────────────────────────
# Username / telefon yordamchilari
# ──────────────────────────────────────────────────────────────────────

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # o'zbek kirill harflari
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}  # fmt: skip

USERNAME_MIN = 3
USERNAME_MAX = 30
# Avtomatik username'ga tasodifiy raqam qo'shish uchun joy qoldiramiz.
USERNAME_BASE_MAX = 24
RESERVED_USERNAMES = frozenset(
    {"admin", "administrator", "root", "support", "enwis", "moderator", "system", "null"}
)


def to_ascii(text: str) -> str:
    """Kirill/diakritikli matnni ASCII lotinga o'tkazadi (qolganini tashlab ketadi)."""
    out = "".join(_CYR_TO_LAT.get(ch, ch) for ch in text.lower())
    return unicodedata.normalize("NFKD", out).encode("ascii", "ignore").decode()


def slugify_username(text: str | None, max_len: int = USERNAME_BASE_MAX) -> str:
    """'Ali Valiyev' -> 'ali.valiyev', 'Ғулом_01' -> 'gulom_01'.

    Natija faqat [a-z0-9._] dan iborat (login/profil validatori bilan bir xil).
    Juda qisqa chiqsa ham bo'sh/qisqa holda qaytadi — chaqiruvchi suffix qo'shadi.
    """
    if not text:
        return ""
    s = to_ascii(text)
    s = re.sub(r"[^a-z0-9._]+", ".", s)
    s = re.sub(r"\.{2,}", ".", s).strip(".")
    return s[:max_len].strip(".")


def digits_only(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", str(phone))
    return d or None


def phone_variants(phone: str) -> list[str]:
    """Bazada telefon '998…' ham, '+998…' ham bo'lishi mumkin — ikkalasini qidiramiz."""
    d = digits_only(phone) or ""
    return [d, f"+{d}"] if d else []


# ──────────────────────────────────────────────────────────────────────
# Telegram: eski Login Widget (HMAC, secret = SHA256(bot_token))
# ──────────────────────────────────────────────────────────────────────


def verify_telegram_widget_payload(data: dict, bot_token: str, max_age: int = 86400) -> dict:
    if not bot_token:
        raise SocialAuthError("Telegram login is not configured", 503)
    data = dict(data)
    received = data.pop("hash", None)
    if not received:
        raise SocialAuthError("Missing Telegram hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, str(received)):
        raise SocialAuthError("Invalid Telegram signature")
    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        auth_date = 0
    if time.time() - auth_date > max_age:
        raise SocialAuthError("Telegram login data has expired — try again")
    return data


def telegram_profile_from_widget(data: dict) -> SocialProfile:
    if data.get("id") is None:
        raise SocialAuthError("Telegram data has no user id", 400)
    first = (data.get("first_name") or "").strip() or None
    last = (data.get("last_name") or "").strip() or None
    full = " ".join(p for p in (first, last) if p) or None
    return SocialProfile(
        provider="telegram",
        provider_id=str(data["id"]),
        full_name=full,
        first_name=first,
        last_name=last,
        username_hint=(data.get("username") or None),
        avatar=(data.get("photo_url") or None),
        locale=(data.get("language_code") or None),
    )


# ──────────────────────────────────────────────────────────────────────
# Telegram: Mini App initData (web3.enwis.uz)
# ──────────────────────────────────────────────────────────────────────


def verify_telegram_webapp_init_data(
    init_data: str, bot_token: str, max_age: int = 86400
) -> dict:
    """`Telegram.WebApp.initData` ni tekshiradi va `user` JSON'ini qaytaradi.

    secret = HMAC_SHA256("WebAppData", bot_token); hash = HMAC_SHA256(secret, data_check_string).
    """
    if not bot_token:
        raise SocialAuthError("Telegram login is not configured", 503)

    # Qo'lda parse qilamiz: parse_qsl "+" ni bo'shliqqa aylantirib yuboradi.
    pairs: dict[str, str] = {}
    for part in init_data.split("&"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        pairs[unquote(k)] = unquote(v)

    received = pairs.pop("hash", None)
    if not received:
        raise SocialAuthError("Missing initData hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received):
        raise SocialAuthError("Invalid Telegram WebApp signature")

    try:
        auth_date = int(pairs.get("auth_date", 0))
    except ValueError:
        auth_date = 0
    if time.time() - auth_date > max_age:
        raise SocialAuthError("initData has expired — reopen the Mini App")

    user_json = pairs.get("user")
    if not user_json:
        raise SocialAuthError("initData missing user field")
    try:
        return json.loads(user_json)
    except ValueError as exc:
        raise SocialAuthError("initData user field is malformed") from exc


def telegram_profile_from_webapp_user(user: dict) -> SocialProfile:
    return telegram_profile_from_widget(user)


# ──────────────────────────────────────────────────────────────────────
# Telegram: yangi Login kutubxonasi — OpenID Connect id_token
# https://core.telegram.org/bots/telegram-login
# ──────────────────────────────────────────────────────────────────────

TELEGRAM_ISSUER = "https://oauth.telegram.org"
TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
TELEGRAM_TOKEN_URL = "https://oauth.telegram.org/token"
# BotFather'da imzo algoritmini o'zgartirish mumkin. "none" va HS* hech qachon qabul qilinmaydi.
TELEGRAM_ALGORITHMS = ("RS256", "ES256", "EdDSA", "ES256K")

_JWKS_TTL = 3600.0  # kalitlarni 1 soat keshlaymiz
_JWKS_MIN_REFETCH = 60.0  # noma'lum `kid` bilan spam qilib JWKS'ni urib bo'lmasin


class TelegramOIDC:
    """Telegram id_token'ni JWKS orqali kriptografik tekshiradi."""

    def __init__(self) -> None:
        self._keys: list[dict] | None = None
        self._fetched_at: float = 0.0

    def reset_cache(self) -> None:
        self._keys = None
        self._fetched_at = 0.0

    async def _fetch_jwks(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(TELEGRAM_JWKS_URL)
                resp.raise_for_status()
                keys = resp.json().get("keys") or []
        except Exception as exc:
            logger.error("Telegram JWKS fetch failed: %s", exc)
            if self._keys:  # eskirgan bo'lsa ham keshdagisi bilan davom etamiz
                return self._keys
            raise SocialAuthError("Telegram bilan bog'lanib bo'lmadi, qayta urinib ko'ring", 502) from exc
        self._keys = keys
        self._fetched_at = time.monotonic()
        return keys

    async def _get_keys(self, *, force: bool = False) -> list[dict]:
        age = time.monotonic() - self._fetched_at
        if self._keys is not None and age < _JWKS_TTL and not force:
            return self._keys
        if force and self._keys is not None and age < _JWKS_MIN_REFETCH:
            return self._keys
        return await self._fetch_jwks()

    async def _find_key(self, kid: str | None, alg: str):
        keys = await self._get_keys()
        match = [k for k in keys if kid is None or k.get("kid") == kid]
        if not match and kid is not None:
            keys = await self._get_keys(force=True)  # kalit aylantirilgan bo'lishi mumkin
            match = [k for k in keys if k.get("kid") == kid]
        if not match or (kid is None and len(match) != 1):
            raise SocialAuthError("Unknown Telegram signing key")
        jwk = match[0]
        if jwk.get("alg") and jwk["alg"] != alg:
            raise SocialAuthError("Telegram token algorithm mismatch")
        try:
            return pyjwt.PyJWK.from_dict(jwk).key
        except Exception as exc:
            raise SocialAuthError("Unsupported Telegram signing key") from exc

    async def verify_id_token(self, token: str, client_id: str) -> dict:
        if not client_id:
            raise SocialAuthError("Telegram login is not configured", 503)
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.PyJWTError as exc:
            raise SocialAuthError("Invalid Telegram token") from exc
        alg = header.get("alg")
        if alg not in TELEGRAM_ALGORITHMS:
            raise SocialAuthError("Unsupported Telegram token algorithm")

        key = await self._find_key(header.get("kid"), alg)
        try:
            claims = pyjwt.decode(
                token,
                key=key,
                algorithms=[alg],
                issuer=TELEGRAM_ISSUER,
                options={"verify_aud": False, "require": ["exp", "iat", "iss", "sub"]},
                leeway=60,
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise SocialAuthError("Telegram token has expired — try again") from exc
        except pyjwt.PyJWTError as exc:
            logger.warning("Invalid Telegram id_token: %s", exc)
            raise SocialAuthError("Invalid Telegram token") from exc

        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if str(client_id) not in {str(a) for a in auds if a is not None}:
            raise SocialAuthError("Telegram token was issued for another application")
        return claims

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
        code_verifier: str | None = None,
    ) -> str:
        """Authorization Code (+PKCE) oqimi: code -> id_token. Faqat server tomonda."""
        if not client_id or not client_secret:
            raise SocialAuthError("Telegram code login is not configured", 503)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    TELEGRAM_TOKEN_URL,
                    data=form,
                    headers={"Authorization": f"Basic {basic}"},
                )
        except Exception as exc:
            logger.error("Telegram token exchange failed: %s", exc)
            raise SocialAuthError("Telegram bilan bog'lanib bo'lmadi, qayta urinib ko'ring", 502) from exc
        if resp.status_code != 200:
            logger.warning("Telegram token endpoint: %s %s", resp.status_code, resp.text[:200])
            raise SocialAuthError("Telegram login code is invalid or expired")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise SocialAuthError("Telegram did not return an id_token")
        return id_token


telegram_oidc = TelegramOIDC()


def telegram_profile_from_claims(claims: dict) -> SocialProfile:
    """id_token claim'laridan profil. `id` (Telegram user id) faqat `profile` scope bilan keladi."""
    tg_id = claims.get("id")
    if tg_id is None:
        raise SocialAuthError(
            "Telegram token has no profile data — request the 'profile' scope", 400
        )
    given = (claims.get("given_name") or "").strip() or None
    family = (claims.get("family_name") or "").strip() or None
    full = (claims.get("name") or "").strip() or " ".join(p for p in (given, family) if p) or None
    phone = digits_only(claims.get("phone_number"))
    return SocialProfile(
        provider="telegram",
        provider_id=str(tg_id),
        full_name=full,
        first_name=given,
        last_name=family,
        username_hint=(claims.get("preferred_username") or None),
        avatar=(claims.get("picture") or None),
        phone=phone,
        # Telegram faqat tasdiqlangan raqamni beradi.
        phone_verified=bool(phone) and bool(claims.get("phone_number_verified", True)),
    )


# ── Telegram nonce (replay'ga qarshi, ixtiyoriy) ──────────────────────
# Format: <vaqt hex 8><tasodifiy hex 12><HMAC hex 20> = 40 belgi, faqat hex.

_NONCE_TTL = 600
_used_nonces: dict[str, float] = {}


def make_telegram_nonce(secret: str) -> str:
    payload = f"{int(time.time()):08x}{secrets.token_hex(6)}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:20]
    return payload + sig


def consume_telegram_nonce(nonce: str, secret: str, ttl: int = _NONCE_TTL) -> bool:
    """Imzo + yosh + bir martalik (shu jarayon doirasida) tekshiruvi."""
    if not isinstance(nonce, str) or len(nonce) != 40:
        return False
    payload, sig = nonce[:20], nonce[20:]
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:20]
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        issued = int(payload[:8], 16)
    except ValueError:
        return False
    now = time.time()
    if now - issued > ttl or issued - now > 60:
        return False
    for key, exp in list(_used_nonces.items()):  # eskirganlarini tozalash
        if exp < now:
            _used_nonces.pop(key, None)
    if nonce in _used_nonces:
        return False
    _used_nonces[nonce] = now + ttl
    return True


# ──────────────────────────────────────────────────────────────────────
# Google
# ──────────────────────────────────────────────────────────────────────


def _split_ids(client_ids: list[str] | str) -> list[str]:
    if isinstance(client_ids, str):
        client_ids = client_ids.split(",")
    return [c.strip() for c in client_ids if c and c.strip()]


def verify_google_id_token(token: str, client_ids: list[str] | str) -> dict:
    """SINXRON (tarmoqqa chiqadi) — `asyncio.to_thread` ichida chaqiring."""
    ids = _split_ids(client_ids)
    if not ids:
        raise SocialAuthError("Google login is not configured", 503)
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            None,  # audience'ni pastda o'zimiz (bir nechta client_id bilan) tekshiramiz
            clock_skew_in_seconds=10,
        )
    except Exception as exc:
        logger.warning("Invalid Google token: %s", exc)
        raise SocialAuthError("Invalid Google token") from exc

    if claims.get("aud") not in ids:
        logger.warning("Google token audience mismatch: %s", claims.get("aud"))
        raise SocialAuthError("Google token was issued for another application")
    return claims


async def verify_google_id_token_async(token: str, client_ids: list[str] | str) -> dict:
    return await asyncio.to_thread(verify_google_id_token, token, client_ids)


async def google_claims_from_access_token(access_token: str, client_ids: list[str] | str) -> dict:
    """`useGoogleLogin` (implicit flow) bergan access_token uchun zaxira yo'l."""
    ids = _split_ids(client_ids)
    if not ids:
        raise SocialAuthError("Google login is not configured", 503)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            info = await client.get(
                "https://oauth2.googleapis.com/tokeninfo", params={"access_token": access_token}
            )
            if info.status_code != 200:
                raise SocialAuthError("Invalid Google token")
            tinfo = info.json()
            if tinfo.get("aud") not in ids and tinfo.get("azp") not in ids:
                raise SocialAuthError("Google token was issued for another application")
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise SocialAuthError("Invalid Google token")
            return resp.json()
    except SocialAuthError:
        raise
    except Exception as exc:
        logger.error("Google userinfo failed: %s", exc)
        raise SocialAuthError("Google bilan bog'lanib bo'lmadi, qayta urinib ko'ring", 502) from exc


def google_profile_from_claims(claims: dict) -> SocialProfile:
    sub = claims.get("sub")
    if not sub:
        raise SocialAuthError("Google token has no subject")
    email = (claims.get("email") or "").strip().lower() or None
    given = (claims.get("given_name") or "").strip() or None
    family = (claims.get("family_name") or "").strip() or None
    full = (claims.get("name") or "").strip() or " ".join(p for p in (given, family) if p) or None
    return SocialProfile(
        provider="google",
        provider_id=str(sub),
        full_name=full,
        first_name=given,
        last_name=family,
        email=email,
        email_verified=claims.get("email_verified") in (True, "true", "True"),
        avatar=(claims.get("picture") or None),
        locale=(claims.get("locale") or None),
    )
