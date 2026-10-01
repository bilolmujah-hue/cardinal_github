"""
Cardinal API v5.1
- JWT (access 15min + refresh 7 kun)
- Video upload → Telegram kanalga (@reklama_db)
- Video streaming endpoint (/api/ad/{id}/video) — Range support bilan
- Avto to'lov (userbot orqali)
- Chat YO'Q, Like YO'Q, Ko'rishlar YO'Q
"""
import asyncio
import json
import base64
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal

from aiohttp import web, ClientSession
import aiohttp_cors

from config import BOT, TARIFFS, CURRENCIES, LIMITS, REGIONS
from config import API as API_CFG
from db import Database
from jwt_auth import (
    jwt_middleware, create_access_token, create_refresh_token, decode_token
)

logger = logging.getLogger("API")


def json_ser(obj):
    if isinstance(obj, Decimal): return float(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    raise TypeError(f"{type(obj)}")


def jresp(data, status=200):
    return web.json_response(data, status=status,
                             dumps=lambda x: json.dumps(x, default=json_ser, ensure_ascii=False))


def is_valid_video_data_url(url: str) -> bool:
    if not url or not isinstance(url, str): return False
    if url.startswith("data:video"): return True
    exts = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
    return url.lower().endswith(exts)


class API:
    def __init__(self, db: Database, bot_app):
        self.db = db
        self.bot_app = bot_app  # CardinalBot instansiyasi
        self.app = web.Application(
            client_max_size=API_CFG.MAX_SIZE,
            middlewares=[jwt_middleware, self._err_mw]
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
                allow_credentials=True, expose_headers="*",
                allow_headers="*", allow_methods="*",
            )
        })

        r = [
            # Public
            ("GET",  "/", self.index),
            ("GET",  "/api/stats", self.stats),
            ("GET",  "/api/tariffs", self.tariffs),
            ("GET",  "/api/regions", self.regions),
            ("GET",  "/api/currencies", self.currencies),
            ("GET",  "/api/ads", self.get_ads),
            ("GET",  "/api/feedbacks", self.get_feedbacks),

            # 🔥 VIDEO STREAMING — /api/ad/{id} dan OLDIN qo'yilishi kerak
            ("GET",  "/api/ad/{ad_id}/video", self.stream_video),

            # Ad detail
            ("GET",  "/api/ad/{ad_id}", self.get_ad),

            # Auth
            ("POST", "/api/auth/telegram", self.auth_telegram),
            ("POST", "/api/auth/refresh", self.auth_refresh),
            ("POST", "/api/auth/logout", self.auth_logout),

            # User (JWT kerak)
            ("GET",  "/api/user/{telegram_id}", self.get_user),
            ("POST", "/api/update-profile", self.update_profile),
            ("GET",  "/api/my-ads/{telegram_id}", self.my_ads),
            ("POST", "/api/create-ad", self.create_ad),
            ("POST", "/api/toggle-save", self.toggle_save),
            ("GET",  "/api/saved-ads/{telegram_id}", self.saved_ads),
            ("GET",  "/api/user-transactions/{telegram_id}", self.user_txs),
            ("POST", "/api/feedbacks/add", self.add_feedback),

            # Topup (avtomatik)
            ("POST", "/api/topup/request", self.topup_request),
            ("GET",  "/api/topup/pending", self.topup_pending),

            # Admin
            ("GET",  "/api/admin/pending-ads", self.admin_pending_ads),
            ("GET",  "/api/admin/all-ads", self.admin_all_ads),
            ("GET",  "/api/admin/users", self.admin_users),
            ("GET",  "/api/admin/blocked", self.admin_blocked),
            ("GET",  "/api/admin/cards", self.admin_cards),
            ("GET",  "/api/admin/topups", self.admin_topups),
            ("POST", "/api/admin/card/add", self.admin_add_card),
            ("POST", "/api/admin/card/del", self.admin_del_card),
            ("POST", "/api/admin/approve-ad", self.admin_approve_ad),
            ("POST", "/api/admin/reject-ad", self.admin_reject_ad),
            ("POST", "/api/admin/delete-ad", self.admin_delete_ad),
            ("POST", "/api/admin/block", self.admin_block),
            ("POST", "/api/admin/unblock", self.admin_unblock),
            ("POST", "/api/admin/broadcast", self.admin_broadcast),
            ("POST", "/api/admin/add-balance", self.admin_add_balance),
            ("POST", "/api/admin/delete-feedback", self.admin_delete_feedback),
        ]

        for method, path, handler in r:
            route = self.app.router.add_route(method, path, handler)
            cors.add(route)

    # ============================================================
    # PUBLIC
    # ============================================================
    async def index(self, req):
        return jresp({
            "app": "Cardinal API", "version": "5.1", "status": "running",
            "max_upload": f"{API_CFG.MAX_SIZE // (1024*1024)} MB"
        })

    async def stats(self, req):
        return jresp(await self.db.get_stats())

    async def tariffs(self, req):
        out = []
        for tid, t in TARIFFS.items():
            out.append({
                "id": tid, "name": t.name, "price": t.price,
                "days": t.days, "type": t.type, "badge": t.badge,
                "channel": t.channel, "webapp": t.webapp,
                "top_hours": getattr(t, "top_hours", 0),
            })
        return jresp(out)

    async def regions(self, req):
        return jresp(REGIONS)

    async def currencies(self, req):
        return jresp(CURRENCIES)

    async def get_ads(self, req):
        cat = req.query.get("category")
        ads = await self.db.get_active_ads(cat)
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

    # ============================================================
    # 🔥 VIDEO STREAMING — Telegram kanaldan proxy (Range support)
    # ============================================================
    async def stream_video(self, req):
        """
        Video stream endpoint.
        - Telegram bot.get_file orqali file_path oladi
        - Telegram CDN dan proxy stream qiladi
        - HTTP Range requests qo'llab-quvvatlanadi (video seek uchun)
        - Client disconnect bo'lsa graceful tugatadi
        """
        ad_id = None
        try:
            ad_id = int(req.match_info["ad_id"])
            ad = await self.db.get_ad(ad_id)
            if not ad or not ad.get("video_file_id"):
                return web.Response(status=404, text="Video topilmadi")

            file_id = ad["video_file_id"]

            # 1. Telegram dan file path olish
            try:
                tg_file = await self.bot_app.bot.get_file(file_id)
                file_path = tg_file.file_path
            except Exception as e:
                logger.error(f"get_file xato (ad #{ad_id}): {e}")
                return web.Response(status=502, text="Video yuklanmadi (Telegram)")

            telegram_url = f"https://api.telegram.org/file/bot{BOT.TOKEN}/{file_path}"

            # 2. Client Range headerini uzatish
            req_headers = {}
            if "Range" in req.headers:
                req_headers["Range"] = req.headers["Range"]

            # 3. Proxy stream
            async with ClientSession() as sess:
                async with sess.get(telegram_url, headers=req_headers) as upstream:
                    if upstream.status not in (200, 206):
                        logger.error(f"Telegram CDN {upstream.status} (ad #{ad_id})")
                        return web.Response(status=502, text="Video CDN xato")

                    # Response tayyorlash
                    resp = web.StreamResponse(status=upstream.status)
                    resp.headers["Content-Type"] = upstream.headers.get("Content-Type", "video/mp4")

                    if "Content-Length" in upstream.headers:
                        resp.headers["Content-Length"] = upstream.headers["Content-Length"]
                    if "Content-Range" in upstream.headers:
                        resp.headers["Content-Range"] = upstream.headers["Content-Range"]

                    resp.headers["Accept-Ranges"] = "bytes"
                    resp.headers["Cache-Control"] = "public, max-age=3600"
                    resp.headers["Access-Control-Allow-Origin"] = "*"

                    try:
                        await resp.prepare(req)
                    except (ConnectionResetError, ConnectionAbortedError):
                        logger.debug(f"Client disconnect (prepare) ad #{ad_id}")
                        return resp

                    # Chunk stream
                    try:
                        async for chunk in upstream.content.iter_chunked(64 * 1024):
                            if not chunk:
                                continue
                            try:
                                await resp.write(chunk)
                            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                                logger.debug(f"Client stream to'xtatdi (ad #{ad_id})")
                                return resp
                            except Exception as e:
                                err_name = type(e).__name__
                                err_str = str(e)
                                if "closing transport" in err_str or "ConnectionReset" in err_name:
                                    logger.debug(f"Stream yopildi (ad #{ad_id}): {e}")
                                    return resp
                                raise

                        try:
                            await resp.write_eof()
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug(f"Upstream xato (ad #{ad_id}): {e}")

                    return resp

        except asyncio.CancelledError:
            logger.debug(f"Stream cancelled (ad #{ad_id})")
            raise
        except Exception as e:
            err_name = type(e).__name__
            err_str = str(e)
            if (
                "ConnectionReset" in err_name
                or "Cannot write to closing transport" in err_str
                or "closing transport" in err_str
                or isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError))
            ):
                logger.debug(f"stream_video (client disconnect): {e}")
                return web.Response(status=499, text="Client closed")
            logger.error(f"stream_video (ad #{ad_id}): {e}", exc_info=True)
            return web.Response(status=500, text="Server xatosi")

    async def get_feedbacks(self, req):
        return jresp(await self.db.get_feedbacks())

    # ============================================================
    # AUTH
    # ============================================================
    async def auth_telegram(self, req):
        try:
            data = await req.json()
            init_data = data.get("init_data", "")
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

            access = create_access_token(user["id"], tg_id, user.get("is_admin", False))
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
                    "is_admin": user.get("is_admin", False),
                    "phone": user.get("phone"),
                }
            })
            resp.set_cookie("access_token", access, max_age=900, httponly=True,
                            secure=True, samesite="Strict")
            resp.set_cookie("refresh_token", refresh, max_age=604800, httponly=True,
                            secure=True, samesite="Strict")
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
        u["is_admin"] = (tg == BOT.ADMIN_CHAT_ID)
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
                    "ok": False,
                    "error": "Balans yetarli emas",
                    "need": t.price, "have": user["balance"]
                }, 400)

            video_data = ad_data.get("video_url")
            if not video_data or not is_valid_video_data_url(video_data):
                return jresp({"ok": False, "error": "Faqat video yuklang"}, 400)

            acc = ad_data.get("account_data", {}) or {}

            # Kolleksiya max 101
            try:
                coll = int(acc.get("collection", 0))
                if coll > LIMITS.COLLECTION_MAX:
                    return jresp({"ok": False, "error": f"Kolleksiya max {LIMITS.COLLECTION_MAX}"}, 400)
                acc["collection"] = coll
            except Exception:
                acc["collection"] = 0

            # RP max 50
            acc["rp"] = str(acc.get("rp", ""))[:LIMITS.RP_MAX_CHARS]

            # Mifik kiyimlar son
            try:
                acc["mythic_clothes"] = int(re.sub(r"\D", "", str(acc.get("mythic_clothes", 0))) or 0)
            except Exception:
                acc["mythic_clothes"] = 0

            # Dinamik ro'yxatlar max 25
            for k in ("rare_skins", "x_costume", "guns", "supar_car"):
                arr = acc.get(k) or []
                if isinstance(arr, list):
                    acc[k] = arr[:LIMITS.ADD_LIST_MAX]

            # Guns count
            try:
                acc["guns_count"] = int(re.sub(r"\D", "", str(acc.get("guns_count", 0))) or 0)
            except Exception:
                acc["guns_count"] = len(acc.get("guns") or [])

            # Telefon / username
            phone = (acc.get("phone") or "").strip()
            username = (acc.get("username") or "").strip()
            if not phone and not username:
                return jresp({"ok": False, "error": "Telefon yoki username kiriting"}, 400)
            if phone:
                digits = re.sub(r"\D", "", phone)
                if digits.startswith("998"): digits = digits[3:]
                if len(digits) != 9:
                    return jresp({"ok": False, "error": "Telefon formati +998XXXXXXXXX"}, 400)
                acc["phone"] = digits
            if username:
                if not username.startswith("@"):
                    username = "@" + username
                acc["username"] = username[:64]

            # Valyuta
            cur_code = ad_data.get("currency", "UZS")
            if cur_code not in CURRENCIES:
                cur_code = "UZS"

            # Narx
            try:
                price = int(re.sub(r"\D", "", str(ad_data.get("price", 0))))
            except Exception:
                price = 0
            if price <= 0:
                return jresp({"ok": False, "error": "Narx noto'g'ri"}, 400)

            # Video kanalga yuklash
            file_id = await self._upload_video_to_channel(video_data)
            if not file_id:
                return jresp({"ok": False, "error": "Videoni yuklashda xatolik"}, 500)

            # DB
            expires_at = datetime.now() + timedelta(days=t.days)
            ad_id = await self.db.create_ad(user["id"], {
                "title": f"PUBG Mobile - {acc.get('level', '?')} LVL",
                "video_file_id": file_id,
                "ad_type": t.type,
                "price": price,
                "currency": cur_code,
                "location": ad_data.get("location"),
                "full_location": ad_data.get("full_location"),
                "account_data": acc,
                "tariff": tariff_id,
                "expires_at": expires_at,
            })

            # Balansdan yechish
            await self.db.update_balance(tg, t.price, "spend", f"Reklama #{ad_id}")

            # Adminga yuborish (background)
            ad = await self.db.get_ad(ad_id)
            asyncio.create_task(self.bot_app.notify_admin_new_ad(ad))

            return jresp({"ok": True, "ad_id": ad_id, "paid": t.price})
        except Exception as e:
            logger.error(f"create_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def _upload_video_to_channel(self, data_url: str) -> str | None:
        """data:video/mp4;base64,... → Telegram video kanalga yuklab, file_id qaytaradi"""
        try:
            header, encoded = data_url.split(",", 1)
            raw = base64.b64decode(encoded)
            if len(raw) > API_CFG.MAX_SIZE:
                return None
            from aiogram.types import BufferedInputFile
            vid = BufferedInputFile(raw, filename="ad.mp4")
            msg = await self.bot_app.bot.send_video(BOT.VIDEO_CHANNEL_ID, vid)
            return msg.video.file_id
        except Exception as e:
            logger.error(f"video upload: {e}", exc_info=True)
            return None

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

            existing = await self.db.get_pending_topup(tg)
            if existing:
                return jresp({
                    "ok": True,
                    "request_id": existing["id"],
                    "card_number": existing["card_number"],
                    "amount": existing["amount"],
                    "expires_at": existing["expires_at"].isoformat(),
                    "note": "Avvalgi so'rov hali faol"
                })

            r = await self.db.create_topup_request(tg, amount)
            if not r:
                return jresp({"ok": False, "error": "Karta mavjud emas"}, 500)

            return jresp({
                "ok": True,
                "request_id": r["id"],
                "card_number": r["card_number"],
                "amount": amount,
                "expires_at": r["expires_at"].isoformat(),
                "note": f"{LIMITS.PAYMENT_TIMEOUT_MIN} daqiqa ichida to'lang"
            })
        except Exception as e:
            logger.error(f"topup_request: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_pending(self, req):
        try:
            tg = int(req.query.get("telegram_id", 0))
            r = await self.db.get_pending_topup(tg)
            if not r:
                user = await self.db.get_user(tg)
                return jresp({"ok": True, "status": "paid_or_expired",
                              "balance": user["balance"] if user else 0})
            return jresp({
                "ok": True,
                "status": "waiting",
                "request_id": r["id"],
                "card_number": r["card_number"],
                "amount": r["amount"],
                "expires_at": r["expires_at"].isoformat(),
            })
        except Exception as e:
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

    async def admin_users(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        users = await self.db.get_all_users()
        for u in users:
            u["is_admin"] = (u["telegram_id"] == BOT.ADMIN_CHAT_ID)
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

    async def admin_add_card(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            num = re.sub(r"\D", "", data.get("number", ""))
            if len(num) != 16:
                return jresp({"ok": False, "error": "16 xonali raqam"}, 400)
            ok = await self.db.add_card(num, data.get("holder", "CARDINAL ADMIN"))
            return jresp({"ok": ok})
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
            if not ad: return jresp({"error": "Topilmadi"}, 404)

            t = TARIFFS.get(ad["tariff"], TARIFFS[1])
            top_until = None
            if getattr(t, "top_hours", 0) > 0:
                top_until = datetime.now() + timedelta(hours=t.top_hours)

            async with self.db.pool.acquire() as c:
                await c.execute("UPDATE ads SET top_until=$1 WHERE id=$2", top_until, ad_id)

            await self.db.update_ad_status(ad_id, "ACTIVE")

            if t.channel and ad.get("video_file_id"):
                asyncio.create_task(self.bot_app._post_to_channel(ad))

            try:
                await self.bot_app.bot.send_message(
                    ad["seller_tg"], f"✅ Reklamangiz tasdiqlandi!\n#{ad_id}"
                )
            except Exception:
                pass

            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_reject_ad(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            reason = data.get("reason", "Admin rad etdi")
            ad = await self.db.get_ad(ad_id)
            if not ad: return jresp({"error": "Topilmadi"}, 404)

            await self.db.update_ad_status(ad_id, "REJECTED", reason)
            t = TARIFFS.get(ad["tariff"], TARIFFS[1])
            await self.db.update_balance(ad["seller_tg"], t.price, "topup", "Rad etilgan reklama qaytarildi")
            try:
                await self.bot_app.bot.send_message(
                    ad["seller_tg"], f"❌ Rad etildi.\nSabab: {reason}\nPul qaytarildi."
                )
            except Exception:
                pass
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_delete_ad(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            ad_id = int(data["ad_id"])
            ad = await self.db.get_ad(ad_id)
            if ad and ad.get("channel_msg_id"):
                try:
                    await self.bot_app.bot.delete_message(BOT.CHANNEL_ID, ad["channel_msg_id"])
                except Exception:
                    pass
            await self.db.delete_ad(ad_id)
            return jresp({"ok": True})
        except Exception as e:
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
                    if uid == BOT.ADMIN_CHAT_ID: continue
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
            await self.db.update_balance(tg, amount, "topup", "Admin qo'shdi")
            try:
                await self.bot_app.bot.send_message(
                    tg, f"✅ Balansingiz {amount:,} so'mga to'ldirildi!"
                )
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

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, API_CFG.HOST, API_CFG.PORT)
        await site.start()
        logger.info(f"🌐 API: http://{API_CFG.HOST}:{API_CFG.PORT}")
