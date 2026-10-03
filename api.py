"""
Cardinal API v5.5
- JWT (access 15min + refresh 7 kun)
- Video upload → Telegram kanal
- Video streaming — Range support
- Userbot boshqaruvi
- Topup oqimi: 10 daqiqa, chek yuklash, status polling
- Admin Contacts
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
        self.bot_app = bot_app
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
            ("GET",  "/api/admin-contacts", self.public_admin_contacts),

            # Video streaming
            ("GET",  "/api/ad/{ad_id}/video", self.stream_video),
            ("GET",  "/api/ad/{ad_id}", self.get_ad),

            # Auth
            ("POST", "/api/auth/telegram", self.auth_telegram),
            ("POST", "/api/auth/refresh", self.auth_refresh),
            ("POST", "/api/auth/logout", self.auth_logout),

            # User
            ("GET",  "/api/user/{telegram_id}", self.get_user),
            ("POST", "/api/update-profile", self.update_profile),
            ("GET",  "/api/my-ads/{telegram_id}", self.my_ads),
            ("POST", "/api/create-ad", self.create_ad),
            ("POST", "/api/toggle-save", self.toggle_save),
            ("GET",  "/api/saved-ads/{telegram_id}", self.saved_ads),
            ("GET",  "/api/user-transactions/{telegram_id}", self.user_txs),
            ("POST", "/api/feedbacks/add", self.add_feedback),

            # Topup — YANGI OQIM
            ("POST", "/api/topup/request", self.topup_request),
            ("GET",  "/api/topup/status",  self.topup_status),
            ("POST", "/api/topup/cancel",  self.topup_cancel),
            ("POST", "/api/topup/receipt", self.topup_receipt),

            # Admin
            ("GET",  "/api/admin/pending-ads", self.admin_pending_ads),
            ("GET",  "/api/admin/all-ads", self.admin_all_ads),
            ("GET",  "/api/admin/users", self.admin_users),
            ("GET",  "/api/admin/blocked", self.admin_blocked),
            ("GET",  "/api/admin/cards", self.admin_cards),
            ("GET",  "/api/admin/topups", self.admin_topups),
            ("GET",  "/api/admin/statistics", self.admin_statistics),
            ("GET",  "/api/admin/user/{telegram_id}", self.admin_user_detail),
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
            ("POST", "/api/admin/add-admin", self.admin_add_admin),

            # Admin Contacts
            ("GET",  "/api/admin/contacts", self.admin_list_contacts),
            ("POST", "/api/admin/contacts/add", self.admin_add_contact),
            ("POST", "/api/admin/contacts/delete", self.admin_delete_contact),
            ("POST", "/api/admin/contacts/toggle", self.admin_toggle_contact),

            # Userbot
            ("POST", "/api/admin/userbot/send-code", self.admin_userbot_send_code),
            ("POST", "/api/admin/userbot/verify-code", self.admin_userbot_verify_code),
            ("POST", "/api/admin/userbot/verify-2fa", self.admin_userbot_verify_2fa),
            ("GET",  "/api/admin/userbot/status", self.admin_userbot_status),
            ("POST", "/api/admin/userbot/logout", self.admin_userbot_logout),
        ]

        for method, path, handler in r:
            route = self.app.router.add_route(method, path, handler)
            cors.add(route)

    # ============================================================
    # PUBLIC
    # ============================================================
    async def index(self, req):
        return jresp({
            "app": "Cardinal API", "version": "5.5", "status": "running",
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

    # ============================================================
    # VIDEO STREAMING
    # ============================================================
    async def stream_video(self, req):
        ad_id = None
        try:
            ad_id = int(req.match_info["ad_id"])
            ad = await self.db.get_ad(ad_id)
            if not ad or not ad.get("video_file_id"):
                return web.Response(status=404, text="Video topilmadi")

            file_id = ad["video_file_id"]

            try:
                tg_file = await self.bot_app.bot.get_file(file_id)
                file_path = tg_file.file_path
            except Exception as e:
                logger.error(f"get_file xato (ad #{ad_id}): {e}")
                return web.Response(status=502, text="Video yuklanmadi")

            telegram_url = f"https://api.telegram.org/file/bot{BOT.TOKEN}/{file_path}"

            req_headers = {}
            if "Range" in req.headers:
                req_headers["Range"] = req.headers["Range"]

            async with ClientSession() as sess:
                async with sess.get(telegram_url, headers=req_headers) as upstream:
                    if upstream.status not in (200, 206):
                        return web.Response(status=502, text="Video CDN xato")

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
                        return resp

                    try:
                        async for chunk in upstream.content.iter_chunked(64 * 1024):
                            if not chunk: continue
                            try:
                                await resp.write(chunk)
                            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                                return resp
                            except Exception as e:
                                if "closing transport" in str(e):
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
            raise
        except Exception as e:
            err_str = str(e)
            if "closing transport" in err_str or isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                return web.Response(status=499)
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
            resp.set_cookie("access_token", access, max_age=900, httponly=True, secure=True, samesite="Strict")
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

            video_data = ad_data.get("video_url")
            if not video_data or not is_valid_video_data_url(video_data):
                return jresp({"ok": False, "error": "Faqat video yuklang"}, 400)

            acc = ad_data.get("account_data", {}) or {}

            try:
                coll = int(acc.get("collection", 0))
                if coll > LIMITS.COLLECTION_MAX:
                    return jresp({"ok": False, "error": f"Kolleksiya max {LIMITS.COLLECTION_MAX}"}, 400)
                acc["collection"] = coll
            except Exception:
                acc["collection"] = 0

            acc["rp"] = str(acc.get("rp", ""))[:LIMITS.RP_MAX_CHARS]

            try:
                acc["mythic_clothes"] = int(re.sub(r"\D", "", str(acc.get("mythic_clothes", 0))) or 0)
            except Exception:
                acc["mythic_clothes"] = 0

            for k in ("rare_skins", "x_costume", "guns", "supar_car"):
                arr = acc.get(k) or []
                if isinstance(arr, list):
                    acc[k] = arr[:LIMITS.ADD_LIST_MAX]

            try:
                acc["guns_count"] = int(re.sub(r"\D", "", str(acc.get("guns_count", 0))) or 0)
            except Exception:
                acc["guns_count"] = len(acc.get("guns") or [])

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
                if not username.startswith("@"): username = "@" + username
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

            file_id = await self._upload_video_to_channel(video_data)
            if not file_id:
                return jresp({"ok": False, "error": "Videoni yuklashda xatolik"}, 500)

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

            await self.db.update_balance(tg, t.price, "spend", f"Reklama #{ad_id}")

            ad = await self.db.get_ad(ad_id)
            asyncio.create_task(self.bot_app.notify_admin_new_ad(ad))

            return jresp({"ok": True, "ad_id": ad_id, "paid": t.price})
        except Exception as e:
            logger.error(f"create_ad: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def _upload_video_to_channel(self, data_url: str) -> str | None:
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
    # TOPUP — YANGI OQIM
    # ============================================================
    async def topup_request(self, req):
        """10 daqiqalik so'rov yaratish."""
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
                "amount": amount,
                "expires_at": r["expires_at"].isoformat() + "Z",
                "timeout_minutes": 10,
            })
        except Exception as e:
            logger.error(f"topup_request: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_status(self, req):
        """
        Hozirgi topup status + vaqt + chek + status.
        Frontend har 3 sekundda chaqiradi.
        """
        try:
            tg = int(req.query.get("telegram_id", 0))
            r = await self.db.get_pending_topup(tg)
            if not r:
                # Oxirgi so'rovni olish
                async with self.db.pool.acquire() as c:
                    u = await self.db.get_user(tg)
                    if u:
                        last = await c.fetchrow("""
                            SELECT * FROM topup_requests WHERE user_id=$1
                            ORDER BY created_at DESC LIMIT 1
                        """, u["id"])
                        if last and last["status"] in ("COMPLETED", "CANCELLED", "EXPIRED", "REJECTED"):
                            # Balansni yangilash
                            fresh_user = await self.db.get_user(tg)
                            return jresp({
                                "ok": True,
                                "status": last["status"].lower(),
                                "amount": last["amount"],
                                "reject_reason": last.get("reject_reason"),
                                "balance": fresh_user["balance"] if fresh_user else 0,
                            })
                return jresp({"ok": True, "status": "none"})

            # Sekundlar qolgan
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
                "amount": r["amount"],
                "expires_at": r["expires_at"].isoformat() + "Z",
                "left_seconds": left_sec,
                "has_receipt": bool(r.get("receipt_url")),
            })
        except Exception as e:
            logger.error(f"topup_status: {e}", exc_info=True)
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_cancel(self, req):
        """Foydalanuvchi bekor qildi."""
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            await self.db.cancel_topup(tg)
            return jresp({"ok": True})
        except Exception as e:
            return jresp({"ok": False, "error": str(e)}, 400)

    async def topup_receipt(self, req):
        """
        Foydalanuvchi chekni yukladi.
        - Agar userbot allaqachon to'lovni aniqlagan (MATCHED) → balans qo'shiladi.
        - Aks holda → adminga yuboriladi, qo'lda tekshiriladi.
        """
        try:
            data = await req.json()
            tg = int(data["telegram_id"])
            receipt_url = data.get("receipt_url")
            if not receipt_url:
                return jresp({"ok": False, "error": "Chek yo'q"}, 400)

            result = await self.db.submit_receipt(tg, receipt_url)
            if not result.get("ok"):
                return jresp({"ok": False, "error": "So'rov topilmadi"}, 400)

            # Adminga rasmni yuborish
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
                        "🎉 <b>Siz endi adminsiz!</b>\n\n"
                        "Web App ni qayta ochsangiz — admin panel ko'rinadi.",
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
                return jresp({"ok": False, "error": "16 xonali raqam"}, 400)
            ok = await self.db.add_card(num_str, data.get("holder", "CARDINAL ADMIN"))
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

    # ============================================================
    # ADMIN CONTACTS
    # ============================================================
    async def public_admin_contacts(self, req):
        """Hamma ko'ra oladi — adminlar ro'yxati."""
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
                return jresp({"ok": False, "error": "Telefon raqam kiriting"}, 400)
            result = await self.bot_app.userbot.send_code(phone)
            return jresp(result)
        except Exception as e:
            logger.error(f"userbot send_code: {e}")
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_verify_code(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            phone = (data.get("phone") or "").strip()
            code = (data.get("code") or "").strip()
            if not phone or not code:
                return jresp({"ok": False, "error": "Telefon va kod kerak"}, 400)
            result = await self.bot_app.userbot.verify_code(phone, code)
            return jresp(result)
        except Exception as e:
            logger.error(f"userbot verify_code: {e}")
            return jresp({"ok": False, "error": str(e)}, 400)

    async def admin_userbot_verify_2fa(self, req):
        if not self._is_admin_req(req): return jresp({"error": "Ruxsat yo'q"}, 403)
        try:
            data = await req.json()
            phone = (data.get("phone") or "").strip()
            password = (data.get("password") or "").strip()
            if not phone or not password:
                return jresp({"ok": False, "error": "Telefon va parol kerak"}, 400)
            result = await self.bot_app.userbot.verify_2fa(phone, password)
            return jresp(result)
        except Exception as e:
            logger.error(f"userbot verify_2fa: {e}")
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
        logger.info(f"🌐 API: http://{API_CFG.HOST}:{API_CFG.PORT}")
