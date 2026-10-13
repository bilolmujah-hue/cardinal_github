"""
Cardinal API v7.6 — Cloudflare R2 (server-side upload, CORS yo'q)
- Video server orqali R2'ga yuklanadi (CORS muammosi yo'q)
- Stream: R2'ga redirect (Railway egress tejaydi)
- Video metadata PostgreSQL'da
- Barcha endpointlar to'liq
"""
import asyncio
import json
import base64
import logging
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from aiohttp import web, ClientSession
import aiohttp_cors
import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from config import BOT, TARIFFS, CURRENCIES, LIMITS, REGIONS, R2
from config import API as API_CFG
from db import Database
from jwt_auth import (
    jwt_middleware, create_access_token, create_refresh_token, decode_token
)

logger = logging.getLogger("API")


# ============================================================
# YORDAMCHI
# ============================================================
def json_ser(obj):
    if isinstance(obj, Decimal): return float(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    raise TypeError(f"{type(obj)}")


def jresp(data, status=200):
    return web.json_response(
        data, status=status,
        dumps=lambda x: json.dumps(x, default=json_ser, ensure_ascii=False)
    )


def is_valid_image_data_url(url: str) -> bool:
    if not url or not isinstance(url, str): return False
    return url.startswith("data:image/")


def generate_r2_key(user_id, ext="mp4"):
    return f"videos/{uuid.uuid4().hex}.{ext}"


def guess_ext(mime_type):
    if not mime_type: return "mp4"
    mime_type = mime_type.lower()
    if "mp4" in mime_type: return "mp4"
    if "quicktime" in mime_type or "mov" in mime_type: return "mov"
    if "webm" in mime_type: return "webm"
    if "matroska" in mime_type: return "mkv"
    if "x-m4v" in mime_type: return "m4v"
    if "3gpp" in mime_type: return "3gp"
    if "avi" in mime_type: return "avi"
    return "mp4"


# ============================================================
# R2 CLIENT (singleton)
# ============================================================
_r2_client = None

def get_r2_client():
    global _r2_client
    if _r2_client is None:
        _r2_client = boto3.client(
            "s3",
            endpoint_url=R2.ENDPOINT,
            aws_access_key_id=R2.ACCESS_KEY,
            aws_secret_access_key=R2.SECRET_KEY,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
            region_name="auto",
        )
    return _r2_client


# ============================================================
# API
# ============================================================
class API:
    def __init__(self, db: Database, bot_app):
        self.db = db
        self.bot_app = bot_app
        self.app = web.Application(
            client_max_size=API_CFG.MAX_SIZE,
            middlewares=[self._err_mw, jwt_middleware]
        )
        self._routes()

    @web.middleware
    async def _err_mw(self, request, handler):
        try:
            return await handler(request)
        except web.HTTPRequestEntityTooLarge:
            return jresp({"ok": False, "error": "Fayl juda katta (max 200 MB)"}, 413)
        except web.HTTPException as e:
            return jresp({"ok": False, "error": f"HTTP {e.status}"}, e.status)
        except Exception as e:
            logger.error(f"API err: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 500)

    def _routes(self):
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*",
            )
        })

        r = [
            # Public
            ("GET",   "/", self.index),
            ("GET",   "/api/stats", self.stats),
            ("GET",   "/api/tariffs", self.tariffs),
            ("GET",   "/api/regions", self.regions),
            ("GET",   "/api/currencies", self.currencies),
            ("GET",   "/api/settings", self.public_settings),
            ("GET",   "/api/ads", self.get_ads),
            ("GET",   "/api/feedbacks", self.get_feedbacks),
            ("GET",   "/api/admin-contacts", self.public_admin_contacts),

            # Ad detail
            ("GET",   "/api/ad/{ad_id}", self.get_ad),

            # Video upload (server orqali R2'ga)
            ("POST",  "/api/upload-video", self.upload_video),

            # Auth
            ("POST",  "/api/auth/telegram", self.auth_telegram),
            ("POST",  "/api/auth/refresh", self.auth_refresh),
            ("POST",  "/api/auth/logout", self.auth_logout),

            # User
            ("GET",   "/api/user/{telegram_id}", self.get_user),
            ("POST",  "/api/update-profile", self.update_profile),
            ("GET",   "/api/my-ads/{telegram_id}", self.my_ads),
            ("POST",  "/api/create-ad", self.create_ad),
            ("POST",  "/api/mark-sold", self.mark_sold),
            ("POST",  "/api/toggle-save", self.toggle_save),
            ("GET",   "/api/saved-ads/{telegram_id}", self.saved_ads),
            ("GET",   "/api/user-transactions/{telegram_id}", self.user_txs),
            ("POST",  "/api/feedbacks/add", self.add_feedback),

            # VIP
            ("POST",  "/api/create-vip-request", self.create_vip_request),

            # Topup
            ("POST",  "/api/topup/request", self.topup_request),
            ("GET",   "/api/topup/status", self.topup_status),
            ("POST",  "/api/topup/cancel", self.topup_cancel),
            ("POST",  "/api/topup/receipt", self.topup_receipt),
            ("POST",  "/api/topup/dismiss", self.topup_dismiss),

            # Admin
            ("GET",   "/api/admin/pending-ads", self.admin_pending_ads),
            ("GET",   "/api/admin/all-ads", self.admin_all_ads),
            ("GET",   "/api/admin/ads-with-pin", self.admin_ads_with_pin),
            ("GET",   "/api/admin/users", self.admin_users),
            ("GET",   "/api/admin/blocked", self.admin_blocked),
            ("GET",   "/api/admin/cards", self.admin_cards),
            ("GET",   "/api/admin/topups", self.admin_topups),
            ("GET",   "/api/admin/statistics", self.admin_statistics),
            ("GET",   "/api/admin/user/{telegram_id}", self.admin_user_detail),
            ("POST",  "/api/admin/card/add", self.admin_add_card),
            ("POST",  "/api/admin/card/del", self.admin_del_card),
            ("POST",  "/api/admin/approve-ad", self.admin_approve_ad),
            ("POST",  "/api/admin/reject-ad", self.admin_reject_ad),
            ("POST",  "/api/admin/delete-ad", self.admin_delete_ad),
            ("POST",  "/api/admin/block", self.admin_block),
            ("POST",  "/api/admin/unblock", self.admin_unblock),
            ("POST",  "/api/admin/broadcast", self.admin_broadcast),
            ("POST",  "/api/admin/add-balance", self.admin_add_balance),
            ("POST",  "/api/admin/delete-feedback", self.admin_delete_feedback),
            ("POST",  "/api/admin/add-admin", self.admin_add_admin),
            ("GET",   "/api/admin/settings", self.admin_get_settings),
            ("POST",  "/api/admin/settings/set-days", self.admin_set_days),
            ("POST",  "/api/admin/settings/set-kanal-interval", self.admin_set_kanal_interval),

            # Admin — Thumbnail / PIN / Edit
            ("POST",  "/api/admin/ad/set-thumbnail", self.admin_set_thumbnail),
            ("POST",  "/api/admin/ad/toggle-pin", self.admin_toggle_pin),
            ("POST",  "/api/admin/ad/reorder-pins", self.admin_reorder_pins),
            ("POST",  "/api/admin/ad/edit", self.admin_edit_ad),

            # Admin Contacts
            ("GET",   "/api/admin/contacts", self.admin_list_contacts),
            ("POST",  "/api/admin/contacts/add", self.admin_add_contact),
            ("POST",  "/api/admin/contacts/delete", self.admin_delete_contact),
            ("POST",  "/api/admin/contacts/toggle", self.admin_toggle_contact),

            # Userbot
            ("POST",  "/api/admin/userbot/send-code", self.admin_userbot_send_code),
            ("POST",  "/api/admin/userbot/verify-code", self.admin_userbot_verify_code),
            ("POST",  "/api/admin/userbot/verify-2fa", self.admin_userbot_verify_2fa),
            ("GET",   "/api/admin/userbot/status", self.admin_userbot_status),
            ("POST",  "/api/admin/userbot/logout", self.admin_userbot_logout),
        ]

        for method, path, handler in r:
            try:
                route = self.app.router.add_route(method, path, handler)
                try:
                    cors.add(route)
                except Exception as e:
                    logger.warning(f"CORS add skip: {method} {path}: {e}")
            except Exception as e:
                logger.warning(f"Route add: {method} {path}: {e}")

        # VIDEO REDIRECT — GET + HEAD
        try:
            video_route = self.app.router.add_get(
                "/api/ad/{ad_id}/video",
                self.stream_video,
                allow_head=True
            )
            cors.add(video_route)
            logger.info("Video route qo'shildi (GET + HEAD) — R2 redirect")
        except Exception as e:
            logger.error(f"Video route xato: {e}")

    # ============================================================
    # PUBLIC
    # ============================================================
    async def index(self, req):
        return jresp({
            "app": "Cardinal API",
            "version": "7.6",
            "status": "running",
            "storage": "Cloudflare R2",
            "max_video_mb": R2.MAX_VIDEO_SIZE // (1024*1024),
        })

    async def stats(self, req):
        return jresp(await self.db.get_stats())

    async def public_settings(self, req):
        days = await self.db.get_ad_days()
        interval = await self.db.get_kanal_interval_min()
        return jresp({
            "ad_days": days,
            "kanal_interval_min": interval,
            "timeout_min": LIMITS.PAYMENT_TIMEOUT_MIN,
            "max_video_mb": R2.MAX_VIDEO_SIZE // (1024*1024),
            "max_video_duration": R2.MAX_VIDEO_DURATION,
        })

    async def tariffs(self, req):
        days = await self.db.get_ad_days()
        out = []
        for tid, t in TARIFFS.items():
            out.append({
                "id": tid, "name": t.name, "price": t.price,
                "days": days, "type": t.type, "badge": t.badge,
                "channel": t.channel, "webapp": t.webapp,
                "r2_storage": getattr(t, "r2_storage", False),
                "top_hours": getattr(t, "top_hours", 0),
                "manual": getattr(t, "manual", False),
            })
        return jresp(out)

    async def regions(self, req):
        return jresp(REGIONS)

    async def currencies(self, req):
        return jresp(CURRENCIES)

    async def get_ads(self, req):
        ads = await self.db.get_active_ads()
        tg = req.query.get("telegram_id")
        if tg:
            try:
                saved_ids = {a["id"] for a in await self.db.get_saved(int(tg))}
                for a in ads:
                    a["is_saved"] = a["id"] in saved_ids
            except Exception:
                pass
        return jresp(ads)

    async def get_ad(self, req):
        aid = int(req.match_info["ad_id"])
        ad = await self.db.get_ad(aid)
        if not ad:
            return jresp({"error": "Topilmadi"}, 404)
        await self.db.increment_views(aid)
        tg = req.query.get("telegram_id")
        if tg:
            try:
                saved = await self.db.get_saved(int(tg))
                ad["is_saved"] = any(x["id"] == aid for x in saved)
            except Exception:
                ad["is_saved"] = False
        return jresp(ad)

    async def get_feedbacks(self, req):
        return jresp(await self.db.get_feedbacks())

    # ============================================================
    # VIDEO STREAM (R2 redirect)
    # ============================================================
    async def stream_video(self, req):
        try:
            ad_id = int(req.match_info["ad_id"])
            ad = await self.db.get_ad(ad_id)
            if not ad or not ad.get("r2_key"):
                return web.Response(status=404, text="Video topilmadi")

            r2_key = ad["r2_key"]

            if R2.PUBLIC_URL:
                url = f"{R2.PUBLIC_URL}/{r2_key}"
                raise web.HTTPFound(url)

            try:
                client = get_r2_client()
                url = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": R2.BUCKET, "Key": r2_key},
                    ExpiresIn=R2.PRESIGN_DOWNLOAD_EXPIRE,
                )
                raise web.HTTPFound(url)
            except ClientError as e:
                logger.error(f"presign download xato: {e}")
                return web.Response(status=502, text="Video mavjud emas")

        except web.HTTPFound:
            raise
        except Exception as e:
            logger.error(f"stream_video: {e}", exc_info=True)
            return web.Response(status=500, text="Server xatosi")

    # ============================================================
    # VIDEO UPLOAD — Server orqali R2'ga (CORS kerak emas!)
    # ============================================================
    async def upload_video(self, req):
        """
        Multipart faylni qabul qilib, R2'ga yuklaydi.
        Frontend → Railway → R2 (CORS umuman ishtirok etmaydi).
        """
        try:
            reader = await req.multipart()
            if not reader:
                return jresp({"ok": False, "error": "Fayl yuborilmadi"}, 400)

            file_data = None
            telegram_id = None
            filename = "ad.mp4"
            mime_type = "video/mp4"

            while True:
                part = await reader.next()
                if part is None:
                    break

                if part.name == "telegram_id":
                    try:
                        val = await part.text()
                        telegram_id = int(val.strip())
                    except Exception:
                        pass

                elif part.name == "video":
                    filename = getattr(part, "filename", None) or "ad.mp4"
                    try:
                        ct = part.headers.get("Content-Type", "video/mp4")
                        mime_type = ct or "video/mp4"
                    except Exception:
                        mime_type = "video/mp4"

                    chunks = []
                    total = 0
                    MAX = R2.MAX_VIDEO_SIZE
                    while True:
                        chunk = await part.read_chunk(1024 * 512)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX:
                            mb = MAX // (1024 * 1024)
                            return jresp({"ok": False, "error": f"Video {mb} MB dan katta"}, 413)
                        chunks.append(chunk)
                    file_data = b"".join(chunks)

            if not telegram_id:
                return jresp({"ok": False, "error": "telegram_id yo'q"}, 400)

            if not file_data:
                return jresp({"ok": False, "error": "Video bo'sh"}, 400)

            user = await self.db.get_user(telegram_id)
            if not user:
                return jresp({"ok": False, "error": "User topilmadi"}, 404)

            # R2'ga yuklash
            ext = guess_ext(mime_type) or "mp4"
            r2_key = generate_r2_key(telegram_id, ext)

            try:
                client = get_r2_client()
                client.put_object(
                    Bucket=R2.BUCKET,
                    Key=r2_key,
                    Body=file_data,
                    ContentType=mime_type,
                )
            except ClientError as e:
                logger.error(f"R2 put_object xato: {e}")
                return jresp({"ok": False, "error": "R2 yuklash xatosi"}, 500)
            except Exception as e:
                logger.error(f"R2 put_object umumiy xato: {e}", exc_info=True)
                return jresp({"ok": False, "error": "R2 yuklash xatosi"}, 500)

            # DB'ga metadata
            video_id = await self.db.create_video_meta(
                r2_key=r2_key,
                size=len(file_data),
                mime_type=mime_type,
                duration_sec=0,
            )

            logger.info(f"✅ Upload OK: video_id={video_id}, key={r2_key}, size={len(file_data)}")

            return jresp({
                "ok": True,
                "video_id": video_id,
                "r2_key": r2_key,
                "public_url": f"{R2.PUBLIC_URL}/{r2_key}" if R2.PUBLIC_URL else None,
                "size": len(file_data),
            })

        except Exception as e:
            logger.error(f"upload_video: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 500)

    # ============================================================
    # AUTH
    # ============================================================
    async def auth_telegram(self, req):
        try:
            data = await req.json()
            user_data = data.get("user")
            if not user_data or not user_data.get("id"):
                return jresp({"ok": False, "error": "User ma'lumoti yo'q"}, 400)

            tg_id = int(user_data["id"])
            user = await self.db.get_or_create_user(
                telegram_id=tg_id,
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
            )
            if user.get("is_blocked"):
                return jresp({"ok": False, "error": "Siz bloklangansiz"}, 403)

            user = await self.db.get_user(tg_id)
            is_admin = (tg_id == BOT.ADMIN_CHAT_ID) or user.get("is_admin", False)

            access = create_access_token(user["id"], tg_id, is_admin)
            refresh = create_refresh_token(user["id"], tg_id)

            resp = jresp({
                "ok": True,
                "access_token": access,
                "refresh_token": refresh,
                "user": {
                    "id": user["id"],
                    "telegram_id": tg_id,
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "username": user.get("username"),
                    "balance": user.get("balance", 0),
                    "spent": user.get("spent", 0),
                    "avatar": user.get("avatar"),
                    "is_admin": is_admin,
                    "phone": user.get("phone"),
                }
            })
            resp.set_cookie("access_token", access, max_age=3600, httponly=True, secure=True, samesite="Strict")
            resp.set_cookie("refresh_token", refresh, max_age=604800, httponly=True, secure=True, samesite="Strict")
            return resp
        except Exception as e:
            logger.error(f"auth: {e}")
            return jresp({"ok": False, "error": str(e)}, 400)

    async def auth_refresh(self, req):
        try:
            data = await req.json()
            rt = data.get("refresh_token") or req.cookies.get("refresh_token")
            if not rt:
                return jresp({"ok": False, "error": "Refresh yo'q"}, 400)
            payload = decode_token(rt)
            if not payload or payload.get("type") != "refresh":
                return jresp({"ok": False, "error": "Refresh yaroqsiz"}, 401)
            user = await self.db.get_user_by_id(int(payload["sub"]))
            if not user:
                return jresp({"ok": False, "error": "User yo'q"}, 401)
            access = create_access_token(user["id"], user["telegram_id"], user.get("is_admin", False))
            return jresp({"ok": True, "access_token": access})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def auth_logout(self, req):
        resp = jresp({"ok": True})
        resp.del_cookie("access_token")
        resp.del_cookie("refresh_token")
        return resp

    # ============================================================
    # USER
    # ============================================================
    async def get_user(self, req):
        tg = int(req.match_info["telegram_id"])
        jwt_u = req.get("user")
        if jwt_u and int(jwt_u.get("tg", 0)) != tg and not jwt_u.get("adm"):
            return jresp({"error": "Ruxsat yo'q"}, 403)
        u = await self.db.get_user(tg)
        if not u:
            return jresp({"error": "Topilmadi"}, 404)
        u["is_admin"] = (tg == BOT.ADMIN_CHAT_ID) or u.get("is_admin", False)
        return jresp(u)

    async def update_profile(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            jwt_u = req.get("user")
            if jwt_u and int(jwt_u.get("tg", 0)) != tg:
                return jresp({"ok": False, "error": "Ruxsat yo'q"}, 403)
            await self.db.update_profile(
                tg,
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                avatar=data.get("avatar"),
            )
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def my_ads(self, req):
        tg = int(req.match_info["telegram_id"])
        return jresp(await self.db.get_user_ads(tg))

    async def user_txs(self, req):
        tg = int(req.match_info["telegram_id"])
        return jresp(await self.db.get_user_txs(tg))

    async def toggle_save(self, req):
        try:
            data = await req.json()
            r = await self.db.toggle_save(int(data["ad_id"]), int(data["telegram_id"]))
            return jresp(r)
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def saved_ads(self, req):
        tg = int(req.match_info["telegram_id"])
        return jresp(await self.db.get_saved(tg))

    async def add_feedback(self, req):
        try:
            data = await req.json()
            fb_id = await self.db.add_feedback(
                int(data["telegram_id"]), data["text"], int(data.get("rating", 5))
            )
            return jresp({"ok": True, "id": fb_id})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # CREATE AD
    # ============================================================
    async def create_ad(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            jwt_u = req.get("user")
            if jwt_u and int(jwt_u.get("tg", 0)) != tg:
                return jresp({"ok": False, "error": "Ruxsat yo'q"}, 403)

            user = await self.db.get_user(tg)
            if not user:
                return jresp({"error": "User yo'q"}, 404)

            ad_data = data.get("ad_data", {})
            tariff_id = int(ad_data.get("tariff", 1))
            t = TARIFFS.get(tariff_id, TARIFFS[1])

            if user["balance"] < t.price:
                return jresp({
                    "ok": False, "error": "Balans yetarli emas",
                    "need": t.price, "have": user["balance"]
                }, 400)

            video_id = ad_data.get("video_id")
            if not video_id:
                return jresp({"ok": False, "error": "Video yuklanmagan"}, 400)

            video_meta = await self.db.get_video_meta(int(video_id))
            if not video_meta:
                return jresp({"ok": False, "error": "Video topilmadi"}, 404)

            acc = ad_data.get("account_data", {}) or {}

            try:
                lvl = int(acc.get("level", 0))
                if lvl > LIMITS.LVL_MAX:
                    return jresp({"ok": False, "error": f"LVL max {LIMITS.LVL_MAX}"}, 400)
                acc["level"] = lvl
            except Exception:
                acc["level"] = 0

            try:
                coll = int(acc.get("collection", 0))
                if coll > LIMITS.COLLECTION_MAX:
                    return jresp({"ok": False, "error": f"Kolleksiya max {LIMITS.COLLECTION_MAX}"}, 400)
                acc["collection"] = coll
            except Exception:
                acc["collection"] = 0

            try:
                mc = int(re.sub(r"\D", "", str(acc.get("mythic_clothes", 0))) or 0)
                if mc > LIMITS.MYTHIC_MAX:
                    return jresp({"ok": False, "error": f"Mifik kiyimlar max {LIMITS.MYTHIC_MAX}"}, 400)
                acc["mythic_clothes"] = mc
            except Exception:
                acc["mythic_clothes"] = 0

            acc["rp"] = str(acc.get("rp", ""))[:LIMITS.RP_MAX_CHARS]

            for k in ("rare_skins", "x_costume", "guns", "supar_car"):
                arr = acc.get(k) or []
                if isinstance(arr, list):
                    acc[k] = arr[:LIMITS.ADD_LIST_MAX]

            try:
                acc["guns_count"] = int(re.sub(r"\D", "", str(acc.get("guns_count", 0))) or 0)
            except Exception:
                acc["guns_count"] = len(acc.get("guns") or [])

            linked = acc.get("linked") or []
            if isinstance(linked, list):
                acc["linked"] = [str(x).strip().lower()[:30] for x in linked if str(x).strip()][:20]
            else:
                acc["linked"] = []

            phone = (acc.get("phone") or "").strip()
            username = (acc.get("username") or "").strip()
            if not phone and not username:
                return jresp({"ok": False, "error": "Telefon yoki username kiriting"}, 400)
            if phone:
                digits = re.sub(r"\D", "", phone)
                if digits.startswith("998"):
                    digits = digits[3:]
                if len(digits) != 9:
                    return jresp({"ok": False, "error": "Telefon formati +998XXXXXXXXX"}, 400)
                acc["phone"] = digits
            if username:
                if not username.startswith("@"):
                    username = "@" + username
                acc["username"] = username[:64]

            cur_code = ad_data.get("currency", "UZS")
            if cur_code not in CURRENCIES:
                cur_code = "UZS"

            try:
                price = int(re.sub(r"\D", "", str(ad_data.get("price", 0))))
            except Exception:
                price = 0
            if price <= 0:
                return jresp({"ok": False, "error": "Narx noto'g'ri"}, 400)

            days = await self.db.get_ad_days()
            expires_at = datetime.now() + timedelta(days=days)

            ad_id = await self.db.create_ad(user["id"], {
                "title": f"PUBG Mobile - {acc.get('level', '?')} LVL",
                "video_id": int(video_id),
                "ad_type": t.type,
                "price": price,
                "currency": cur_code,
                "location": ad_data.get("location"),
                "full_location": ad_data.get("full_location"),
                "account_data": acc,
                "tariff": tariff_id,
                "expires_at": expires_at,
            })

            await self.db.link_video_to_ad(int(video_id), ad_id)
            await self.db.update_balance(tg, t.price, "spend", f"Reklama #{ad_id}")

            ad = await self.db.get_ad(ad_id)
            asyncio.create_task(self.bot_app.notify_admin_new_ad(ad))

            return jresp({"ok": True, "ad_id": ad_id, "paid": t.price})
        except Exception as e:
            logger.error(f"create_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # MARK SOLD
    # ============================================================
    async def mark_sold(self, req):
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            tg = int(data["telegram_id"])
            jwt_u = req.get("user")
            if jwt_u and int(jwt_u.get("tg", 0)) != tg:
                return jresp({"ok": False, "error": "Ruxsat yo'q"}, 403)

            ad = await self.db.get_ad(ad_id)
            if not ad:
                return jresp({"ok": False, "error": "Topilmadi"}, 404)
            if ad["seller_tg"] != tg:
                return jresp({"ok": False, "error": "Ruxsat yo'q"}, 403)
            if ad["status"] != "ACTIVE":
                return jresp({"ok": False, "error": "Faqat faol reklamalar uchun"}, 400)

            ok = await self.db.mark_ad_sold(ad_id, tg)
            if not ok:
                return jresp({"ok": False, "error": "Belgilanmadi"}, 400)

            if ad.get("channel_msg_id"):
                try:
                    await self.bot_app.delete_channel_post(ad["channel_msg_id"])
                except Exception as e:
                    logger.warning(f"delete_channel_post xato: {e}")

            try:
                await self.bot_app.bot.send_message(
                    tg,
                    f"✅ <b>Reklamangiz sotildi deb belgilandi!</b>\n\n"
                    f"🆔 #{ad_id}\n"
                    f"📢 {ad['title']}\n\n"
                    f"Endi bu e'lon Web App'da ko'rinmaydi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"mark_sold: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # VIP REQUEST
    # ============================================================
    async def create_vip_request(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            jwt_u = req.get("user")
            if jwt_u and int(jwt_u.get("tg", 0)) != tg:
                return jresp({"ok": False, "error": "Ruxsat yo'q"}, 403)

            user = await self.db.get_user(tg)
            if not user:
                return jresp({"ok": False, "error": "User yo'q"}, 404)

            t = TARIFFS[4]
            price = t.price

            if user["balance"] < price:
                return jresp({
                    "ok": False,
                    "error": f"Balansingizda {price:,} so'm yetarli emas".replace(",", " "),
                    "need": price,
                    "have": user["balance"],
                }, 400)

            result = await self.db.create_vip_request(tg, price)
            if not result:
                return jresp({"ok": False, "error": "Xatolik"}, 500)

            try:
                info = {
                    "telegram_id": tg,
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "phone": user.get("phone"),
                    "balance": result["balance"],
                    "price": price,
                    "account_data": data.get("account_data", {}),
                }
                await self.bot_app.notify_admin_vip_request(info)
            except Exception as e:
                logger.error(f"VIP notify error: {e}", exc_info=True)

            return jresp({
                "ok": True,
                "balance": result["balance"],
                "paid": price,
            })
        except Exception as e:
            logger.error(f"create_vip_request: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # TOPUP
    # ============================================================
    async def topup_request(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            amount = int(data["amount"])
            if amount < LIMITS.MIN_TOPUP:
                return jresp({"ok": False, "error": f"Minimal {LIMITS.MIN_TOPUP} so'm"}, 400)

            r = await self.db.create_topup_request(tg, amount)
            if not r:
                return jresp({"ok": False, "error": "Karta mavjud emas"}, 500)

            return jresp({
                "ok": True,
                "request_id": r["id"],
                "card_number": r["card_number"],
                "card_holder": r.get("card_holder") or "CARDINAL ADMIN",
                "amount": amount,
                "expires_at": r["expires_at"].isoformat() + "Z",
                "timeout_minutes": LIMITS.PAYMENT_TIMEOUT_MIN,
            })
        except Exception as e:
            logger.error(f"topup_request: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_status(self, req):
        try:
            tg = int(req.query.get("telegram_id", 0))
            r = await self.db.get_pending_topup(tg)

            if not r:
                async with self.db.pool.acquire() as c:
                    u = await self.db.get_user(tg)
                    if u:
                        last = await c.fetchrow("""
                            SELECT * FROM topup_requests WHERE user_id=$1
                            ORDER BY created_at DESC LIMIT 1
                        """, u["id"])
                        if last and last["status"] in ("COMPLETED", "CANCELLED", "EXPIRED", "REJECTED"):
                            fresh_user = await self.db.get_user(tg)
                            return jresp({
                                "ok": True,
                                "status": last["status"].lower(),
                                "amount": last["amount"],
                                "reject_reason": last.get("reject_reason"),
                                "balance": fresh_user["balance"] if fresh_user else 0,
                            })
                return jresp({"ok": True, "status": "none"})

            left_sec = max(0, int((r["expires_at"] - datetime.now()).total_seconds()))

            status_map = {
                "WAITING": "waiting",
                "MATCHED": "matched",
                "RECEIPT_UPLOADED": "receipt_uploaded",
            }
            return jresp({
                "ok": True,
                "status": status_map.get(r["status"], "waiting"),
                "request_id": r["id"],
                "card_number": r["card_number"],
                "card_holder": r.get("card_holder") or "CARDINAL ADMIN",
                "amount": r["amount"],
                "expires_at": r["expires_at"].isoformat() + "Z",
                "left_seconds": left_sec,
                "has_receipt": bool(r.get("receipt_url")),
            })
        except Exception as e:
            logger.error(f"topup_status: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_dismiss(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            await self.db.mark_topup_seen(tg)
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_cancel(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            await self.db.cancel_topup(tg)
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_receipt(self, req):
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            receipt_url = data.get("receipt_url")
            if not receipt_url:
                return jresp({"ok": False, "error": "Chek yo'q"}, 400)

            result = await self.db.submit_receipt(tg, receipt_url)
            if not result.get("ok"):
                return jresp({"ok": False, "error": "So'rov topilmadi"}, 400)

            try:
                await self.bot_app.send_receipt_to_admin(
                    receipt_url,
                    {
                        "user_name": result.get("user_name"),
                        "phone": result.get("phone"),
                        "telegram_id": result.get("telegram_id"),
                        "amount": result.get("amount"),
                        "request_id": result.get("request_id"),
                    },
                    result.get("completed", False),
                )
            except Exception as e:
                logger.error(f"Admin receipt notify: {e}", exc_info=True)

            return jresp({
                "ok": True,
                "completed": result.get("completed", False),
                "amount": result.get("amount", 0),
            })
        except Exception as e:
            logger.error(f"topup_receipt: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # ADMIN
    # ============================================================
    def _is_admin_req(self, req) -> bool:
        u = req.get("user")
        return bool(u and u.get("adm"))

    async def admin_pending_ads(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        return jresp(await self.db.get_pending_ads())

    async def admin_all_ads(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        return jresp(await self.db.get_active_ads())

    async def admin_ads_with_pin(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            return jresp(await self.db.get_all_ads_with_pin())
        except Exception as e:
            logger.error(f"admin_ads_with_pin: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_users(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        users = await self.db.get_all_users()
        for u in users:
            u["is_admin"] = (u["telegram_id"] == BOT.ADMIN_CHAT_ID) or u.get("is_admin", False)
        return jresp(users)

    async def admin_blocked(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        return jresp(await self.db.get_blocked())

    async def admin_cards(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        return jresp(await self.db.get_cards(active_only=False))

    async def admin_topups(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        async with self.db.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT t.*, u.telegram_id, u.first_name, u.last_name
                FROM transactions t JOIN users u ON u.id=t.user_id
                WHERE t.type='topup' ORDER BY t.created_at DESC LIMIT 100
            """)
            return jresp([dict(r) for r in rows])

    async def admin_statistics(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            return jresp(await self.db.get_statistics())
        except Exception as e:
            logger.error(f"statistics: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_user_detail(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            tg = int(req.match_info["telegram_id"])
            u = await self.db.get_user_full(tg)
            if not u:
                return jresp({"error": "Topilmadi"}, 404)
            return jresp(u)
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_add_admin(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            tg = int(data.get("telegram_id", 0))
            if not tg:
                return jresp({"ok": False, "error": "Chat ID kerak"}, 400)
            user = await self.db.get_user(tg)
            if not user:
                return jresp({"ok": False, "error": "Foydalanuvchi topilmadi"}, 404)
            ok = await self.db.add_admin(tg)
            if ok:
                try:
                    await self.bot_app.bot.send_message(
                        tg,
                        "🎉 <b>Siz endi adminsiz!</b>\n\nWeb App ni qayta ochsangiz — admin panel ko'rinadi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return jresp({"ok": ok})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_add_card(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            num_str = re.sub(r"\D", "", data.get("number", ""))
            if len(num_str) != 16:
                return jresp({"ok": False, "error": "16 xonali raqam kiriting"}, 400)
            holder = (data.get("holder") or "").strip()
            if not holder:
                return jresp({"ok": False, "error": "Karta egasining ism-familiyasini kiriting"}, 400)
            if len(holder) > 100:
                holder = holder[:100]
            ok = await self.db.add_card(num_str, holder.upper())
            if not ok:
                return jresp({"ok": False, "error": "Karta qo'shilmadi"}, 500)
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_del_card(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            await self.db.remove_card(int(data["card_id"]))
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_approve_ad(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            ad = await self.db.get_ad(ad_id)
            if not ad:
                return jresp({"error": "Topilmadi"}, 404)

            t = TARIFFS.get(ad["tariff"], TARIFFS[1])
            top_until = None
            if getattr(t, "top_hours", 0) > 0:
                top_until = datetime.now() + timedelta(hours=t.top_hours)

            async with self.db.pool.acquire() as c:
                await c.execute("UPDATE ads SET top_until=$1 WHERE id=$2", top_until, ad_id)

            await self.db.update_ad_status(ad_id, "ACTIVE")

            if t.channel and ad.get("r2_key"):
                post_at = await self.db.get_next_kanal_slot()
                await self.db.set_ad_post_at(ad_id, post_at)
                asyncio.create_task(self.bot_app.schedule_channel_post(ad_id, post_at))
                logger.info(f"#{ad_id} kanal navbatiga qo'yildi: {post_at}")

            try:
                fresh = await self.db.get_ad(ad_id)
                await self.bot_app.notify_user_approved(fresh, t)
            except Exception as e:
                logger.error(f"notify_user_approved xato: {e}")

            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_approve_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_reject_ad(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            reason = data.get("reason", "Admin rad etdi")
            ad = await self.db.get_ad(ad_id)
            if not ad:
                return jresp({"error": "Topilmadi"}, 404)

            await self.db.update_ad_status(ad_id, "REJECTED", reason)
            t = TARIFFS.get(ad["tariff"], TARIFFS[1])
            await self.db.update_balance(ad["seller_tg"], t.price, "topup", "Rad etilgan reklama qaytarildi")

            # R2'dan video o'chirish
            if ad.get("r2_key"):
                try:
                    client = get_r2_client()
                    client.delete_object(Bucket=R2.BUCKET, Key=ad["r2_key"])
                    logger.info(f"R2 o'chirildi (reject): {ad['r2_key']}")
                except Exception as e:
                    logger.warning(f"R2 delete (reject): {e}")

            if ad.get("video_id"):
                try:
                    await self.db.delete_video_meta(ad["video_id"])
                except Exception as e:
                    logger.warning(f"delete_video_meta: {e}")

            try:
                await self.bot_app.notify_user_rejected(ad, reason, t.price)
            except Exception as e:
                logger.error(f"notify_user_rejected xato: {e}")

            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_reject_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_delete_ad(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            ad = await self.db.get_ad(ad_id)

            if ad and ad.get("channel_msg_id"):
                try:
                    await self.bot_app.delete_channel_post(ad["channel_msg_id"])
                except Exception as e:
                    logger.warning(f"delete_channel_post: {e}")

            if ad and ad.get("r2_key"):
                try:
                    client = get_r2_client()
                    client.delete_object(Bucket=R2.BUCKET, Key=ad["r2_key"])
                    logger.info(f"R2 o'chirildi: {ad['r2_key']}")
                except Exception as e:
                    logger.warning(f"R2 delete: {e}")

            await self.db.delete_ad(ad_id)
            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_delete_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_block(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            await self.db.block_user(int(data["telegram_id"]), data.get("reason"))
            try:
                await self.bot_app.bot.send_message(int(data["telegram_id"]), "🚫 Bloklandingiz")
            except Exception:
                pass
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_unblock(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            await self.db.unblock_user(int(data["telegram_id"]))
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_broadcast(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            text = (data.get("message") or "").strip()
            if not text:
                return jresp({"error": "Xabar bo'sh"}, 400)
            ids = await self.db.get_all_user_ids()

            async def run():
                sent = 0
                for uid in ids:
                    if uid == BOT.ADMIN_CHAT_ID:
                        continue
                    try:
                        await self.bot_app.bot.send_message(uid, text, parse_mode="HTML")
                        sent += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        pass
                logger.info(f"Broadcast: {sent}/{len(ids)}")

            asyncio.create_task(run())
            return jresp({"ok": True, "total": len(ids)})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_add_balance(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            amount = int(data["amount"])
            if amount < 0:
                await self.db.remove_balance(tg, abs(amount))
                msg = f"⚠️ Balansingizdan <b>{abs(amount):,} so'm</b> olib tashlandi"
            else:
                await self.db.update_balance(tg, amount, "topup", "Admin qo'shdi")
                msg = f"✅ Balansingiz <b>{amount:,} so'm</b>ga to'ldirildi!"
            try:
                await self.bot_app.bot.send_message(tg, msg, parse_mode="HTML")
            except Exception:
                pass
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_delete_feedback(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            await self.db.delete_feedback(int(data["feedback_id"]))
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_get_settings(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        days = await self.db.get_ad_days()
        interval = await self.db.get_kanal_interval_min()
        return jresp({"ad_days": days, "kanal_interval_min": interval})

    async def admin_set_days(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            days = int(data.get("days", 15))
            if days < 1: days = 1
            if days > 365: days = 365
            await self.db.set_setting("ad_days", days)
            return jresp({"ok": True, "days": days})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_set_kanal_interval(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            minutes = int(data.get("minutes", 30))
            if minutes < 1: minutes = 1
            if minutes > 1440: minutes = 1440
            await self.db.set_setting("kanal_interval_min", minutes)
            return jresp({"ok": True, "minutes": minutes})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_set_thumbnail(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            thumbnail_url = data.get("thumbnail_url")

            if thumbnail_url is not None:
                if not is_valid_image_data_url(thumbnail_url):
                    return jresp({"ok": False, "error": "Faqat rasm yuklang"}, 400)
                try:
                    header, encoded = thumbnail_url.split(",", 1)
                    if len(encoded) > 2_000_000:
                        return jresp({"ok": False, "error": "Rasm 1.5 MB dan katta"}, 400)
                except Exception:
                    return jresp({"ok": False, "error": "Rasm noto'g'ri"}, 400)

            await self.db.set_ad_thumbnail(ad_id, thumbnail_url)
            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_set_thumbnail: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_toggle_pin(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            result = await self.db.toggle_ad_pin(ad_id)
            if result is None:
                return jresp({"ok": False, "error": "Topilmadi"}, 404)
            return jresp({"ok": True, **result})
        except Exception as e:
            logger.error(f"admin_toggle_pin: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_reorder_pins(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_ids = data.get("ad_ids") or []
            ad_ids = [int(x) for x in ad_ids if str(x).isdigit()]
            await self.db.reorder_pins(ad_ids)
            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_reorder_pins: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_edit_ad(self, req):
        if not self._is_admin_req(req):
            return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            acc = data.get("account_data", {}) or {}

            try:
                lvl = int(acc.get("level", 0) or 0)
                if lvl < 0: lvl = 0
                if lvl > LIMITS.LVL_MAX:
                    return jresp({"ok": False, "error": f"LVL max {LIMITS.LVL_MAX}"}, 400)
                acc["level"] = lvl
            except Exception:
                acc["level"] = 0

            try:
                coll = int(acc.get("collection", 0) or 0)
                if coll < 0: coll = 0
                if coll > LIMITS.COLLECTION_MAX:
                    return jresp({"ok": False, "error": f"Kolleksiya max {LIMITS.COLLECTION_MAX}"}, 400)
                acc["collection"] = coll
            except Exception:
                acc["collection"] = 0

            try:
                mc = int(re.sub(r"\D", "", str(acc.get("mythic_clothes", 0))) or 0)
                if mc > LIMITS.MYTHIC_MAX:
                    return jresp({"ok": False, "error": f"Mifik kiyimlar max {LIMITS.MYTHIC_MAX}"}, 400)
                acc["mythic_clothes"] = mc
            except Exception:
                acc["mythic_clothes"] = 0

            acc["rp"] = str(acc.get("rp", ""))[:LIMITS.RP_MAX_CHARS]

            for k in ("rare_skins", "x_costume", "guns", "supar_car"):
                arr = acc.get(k) or []
                if isinstance(arr, list):
                    cleaned = []
                    for item in arr:
                        s = str(item).strip()
                        if s:
                            cleaned.append(s[:100])
                        if len(cleaned) >= LIMITS.ADD_LIST_MAX:
                            break
                    acc[k] = cleaned
                else:
                    acc[k] = []

            try:
                gc = int(re.sub(r"\D", "", str(acc.get("guns_count", 0))) or 0)
                if gc < 0: gc = 0
                acc["guns_count"] = gc
            except Exception:
                acc["guns_count"] = len(acc.get("guns") or [])

            linked = acc.get("linked") or []
            if isinstance(linked, list):
                cleaned_linked = []
                for item in linked:
                    s = str(item).strip().lower()
                    if s and s not in cleaned_linked:
                        cleaned_linked.append(s[:30])
                    if len(cleaned_linked) >= 20:
                        break
                acc["linked"] = cleaned_linked
            else:
                acc["linked"] = []

            phone = (acc.get("phone") or "").strip()
            if phone:
                digits = re.sub(r"\D", "", phone)
                if digits.startswith("998"):
                    digits = digits[3:]
                if len(digits) != 9:
                    return jresp({"ok": False, "error": "Telefon formati +998XXXXXXXXX"}, 400)
                acc["phone"] = digits
            else:
                acc["phone"] = ""

            username = (acc.get("username") or "").strip()
            if username:
                if not username.startswith("@"):
                    username = "@" + username
                acc["username"] = username[:64]
            else:
                acc["username"] = ""

            price = int(re.sub(r"\D", "", str(data.get("price", 0))) or 0)
            if price <= 0:
                return jresp({"ok": False, "error": "Narx noto'g'ri"}, 400)

            cur_code = data.get("currency", "UZS")
            if cur_code not in CURRENCIES:
                cur_code = "UZS"

            title = (data.get("title") or "").strip()
            if title and len(title) > 255:
                title = title[:255]

            location = (data.get("location") or "").strip() or None
            full_location = (data.get("full_location") or "").strip() or None

            await self.db.update_ad_text(ad_id, {
                "title": title or None,
                "price": price,
                "currency": cur_code,
                "location": location,
                "full_location": full_location,
                "account_data": acc,
            })

            return jresp({"ok": True})
        except Exception as e:
            logger.error(f"admin_edit_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # ADMIN CONTACTS
    # ============================================================
    async def public_admin_contacts(self, req):
        try:
            contacts = await self.db.get_admin_contacts(active_only=True)
            return jresp(contacts)
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_list_contacts(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            return jresp(await self.db.get_admin_contacts(active_only=False))
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_add_contact(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            chat_id = int(data.get("chat_id", 0))
            if not chat_id:
                return jresp({"ok": False, "error": "Chat ID kerak"}, 400)
            ok = await self.db.add_admin_contact(
                chat_id=chat_id,
                username=(data.get("username") or "").strip().lstrip("@") or None,
                first_name=(data.get("first_name") or "").strip() or None,
                last_name=(data.get("last_name") or "").strip() or None,
                info=(data.get("info") or "").strip() or "",
            )
            return jresp({"ok": ok})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_delete_contact(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            await self.db.delete_admin_contact(int(data["contact_id"]))
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_toggle_contact(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            new_state = await self.db.toggle_admin_contact(int(data["contact_id"]))
            return jresp({"ok": True, "is_active": new_state})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # USERBOT
    # ============================================================
    async def admin_userbot_send_code(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            phone = (data.get("phone") or "").strip()
            if not phone:
                return jresp({"ok": False, "error": "Telefon kiriting"}, 400)
            return jresp(await self.bot_app.userbot.send_code(phone))
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_verify_code(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            phone = (data.get("phone") or "").strip()
            code = (data.get("code") or "").strip()
            if not phone or not code:
                return jresp({"ok": False, "error": "Telefon va kod kerak"}, 400)
            return jresp(await self.bot_app.userbot.verify_code(phone, code))
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_verify_2fa(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            phone = (data.get("phone") or "").strip()
            password = (data.get("password") or "").strip()
            if not phone or not password:
                return jresp({"ok": False, "error": "Telefon va parol kerak"}, 400)
            return jresp(await self.bot_app.userbot.verify_2fa(phone, password))
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_status(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            return jresp(await self.bot_app.userbot.get_status())
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_logout(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            return jresp(await self.bot_app.userbot.logout())
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    # ============================================================
    # START
    # ============================================================
    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, API_CFG.HOST, API_CFG.PORT)
        await site.start()
        logger.info(f"✅ API v7.6: http://{API_CFG.HOST}:{API_CFG.PORT}")
