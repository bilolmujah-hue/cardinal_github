import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from aiohttp import web
from config import JWT


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


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


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT.SECRET, algorithms=[JWT.ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ============ AIOHTTP MIDDLEWARE ============
@web.middleware
async def jwt_middleware(request, handler):
    """JWT tekshirish. /api/auth/* va /api/public/* dan tashqari hamma joyda kerak."""
    path = request.path

    # Ochiq endpointlar
    public_paths = (
        "/", "/api/stats", "/api/tariffs",
        "/api/auth/telegram", "/api/auth/refresh",
        "/api/ads", "/api/feedbacks", "/api/public",
    )
    if any(path.startswith(p) for p in public_paths) and not path.startswith("/api/admin"):
        # Agar token bo'lsa, uni parse qilib request ga qo'shamiz (lekin majburiy emas)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            payload = decode_token(auth[7:])
            if payload and payload.get("type") == "access":
                request["user"] = payload
        return await handler(request)

    # Qolganlarida JWT majburiy
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        # Cookie'dan ham tekshiramiz
        token = request.cookies.get("access_token")
        if not token:
            return web.json_response({"ok": False, "error": "Token yo'q"}, status=401)
    else:
        token = auth[7:]

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return web.json_response({"ok": False, "error": "Token yaroqsiz"}, status=401)

    request["user"] = payload

    # Admin tekshiruvi
    if path.startswith("/api/admin") and not payload.get("adm"):
        return web.json_response({"ok": False, "error": "Admin emas"}, status=403)

    return await handler(request)