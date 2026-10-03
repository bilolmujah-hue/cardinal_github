"""
Cardinal JWT v5.6
- access 15 min, refresh 7 kun
- Public pathlar: /api/admin-contacts ham qo'shildi
"""
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from aiohttp import web
from config import JWT


# ============================================================
# PASSWORD
# ============================================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ============================================================
# TOKEN
# ============================================================
def create_access_token(user_id: int, telegram_id: int, is_admin: bool = False) -> str:
    payload = {
        "sub": str(user_id),
        "tg": telegram_id,
        "adm": is_admin,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT.ACCESS_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT.SECRET, algorithm=JWT.ALGORITHM)


def create_refresh_token(user_id: int, telegram_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "tg": telegram_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT.REFRESH_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT.SECRET, algorithm=JWT.ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT.SECRET, algorithms=[JWT.ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ============================================================
# PUBLIC PATHS
# ============================================================
EXACT_PUBLIC_PATHS = (
    "/",
    "/api/stats",
    "/api/tariffs",
    "/api/regions",
    "/api/currencies",
    "/api/ads",
    "/api/feedbacks",
    "/api/admin-contacts",   # 🔥 public — hamma ko'radi
)
PREFIX_PUBLIC_PATHS = (
    "/api/auth/",
    "/api/ad/",
)


# ============================================================
# MIDDLEWARE
# ============================================================
@web.middleware
async def jwt_middleware(request, handler):
    """JWT tekshirish. OPTIONS va public pathlardan tashqari."""

    # CORS preflight
    if request.method == "OPTIONS":
        return await handler(request)

    path = request.path

    is_public = (
        path in EXACT_PUBLIC_PATHS
        or any(path.startswith(p) for p in PREFIX_PUBLIC_PATHS)
    )

    # Token olish
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get("access_token")

    # Public — token ixtiyoriy
    if is_public:
        if token:
            payload = decode_token(token)
            if payload and payload.get("type") == "access":
                request["user"] = payload
        return await handler(request)

    # Qolganlari uchun JWT majburiy
    if not token:
        return web.json_response({"ok": False, "error": "Token yo'q"}, status=401)

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return web.json_response({"ok": False, "error": "Token yaroqsiz"}, status=401)

    request["user"] = payload

    # Admin tekshiruvi
    if path.startswith("/api/admin") and not path.startswith("/api/admin-contacts"):
        if not payload.get("adm"):
            return web.json_response({"ok": False, "error": "Admin emas"}, status=403)

    return await handler(request)
