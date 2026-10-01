"""
@CardXabarBot dan keladigan to'lov xabarlarini o'qib, avtomatik balans qo'shadi.
Session DB dan yuklanadi — admin panel orqali boshqariladi.
"""
import asyncio
import logging
import re
from typing import Optional, Callable, Awaitable, Dict, Any

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpAbridged
from telethon.errors import (
    AuthKeyNotFound, AuthKeyDuplicatedError, SessionRevokedError,
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError,
)

from config import USERBOT

logger = logging.getLogger("Userbot")


class CardXabarWatcher:
    def __init__(self, on_payment: Callable[[int, str, str], Awaitable[dict]], db=None):
        self.on_payment = on_payment
        self.db = db
        self.client: Optional[TelegramClient] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._pending: Dict[str, Dict[str, Any]] = {}  # phone -> {client, hash}

    # ============================================================
    # START (DB dan yuklash)
    # ============================================================
    async def start(self):
        """DB dan session olib, ulanish."""
        if not self.db:
            logger.warning("⚠️ DB ulanmagan — userbot ishga tushmaydi")
            return

        session_str = await self.db.get_userbot_session()
        if not session_str:
            logger.warning("⚠️ DB da userbot session yo'q — admin paneldan qo'shing")
            return

        await self._connect_with_session(session_str.strip())

    async def _connect_with_session(self, session_str: str):
        """Session string bilan ulanish + handlerlarni ro'yxatdan o'tkazish."""
        try:
            self.client = TelegramClient(
                StringSession(session_str),
                USERBOT.API_ID,
                USERBOT.API_HASH,
                device_model="Cardinal",
                system_version="1.0",
                app_version="5.1",
                connection=ConnectionTcpAbridged,
                use_ipv6=False,
                timeout=30,
                retry_delay=3,
                auto_reconnect=True,
                connection_retries=15,
                request_retries=5,
                flood_sleep_threshold=60,
                sequential_updates=False,
            )

            @self.client.on(events.NewMessage(incoming=True))
            async def handler(event):
                await self._on_message(event)

            await self.client.start()
            me = await self.client.get_me()
            logger.info(f"✅ Userbot ishga tushdi: @{me.username or me.id} (ID: {me.id})")

            self._task = asyncio.create_task(self.client.run_until_disconnected())

        except (AuthKeyNotFound, AuthKeyDuplicatedError, SessionRevokedError) as e:
            logger.error(f"❌ Sessiya yaroqsiz: {type(e).__name__}")
            # DB dan o'chirish
            if self.db:
                await self.db.delete_userbot_session()
            self.client = None
        except Exception as e:
            logger.error(f"❌ Userbot ulanish xatosi: {e}")
            self.client = None

    # ============================================================
    # AUTH — admin panel orqali
    # ============================================================
    async def send_code(self, phone: str) -> dict:
        """
        1-qadam: Telefon raqamga kod yuborish.
        """
        try:
            phone = phone.strip()
            if not phone.startswith("+"):
                phone = "+" + phone

            # Eski pending bo'lsa tozalash
            if phone in self._pending:
                try:
                    await self._pending[phone]["client"].disconnect()
                except Exception:
                    pass
                del self._pending[phone]

            client = TelegramClient(
                StringSession(),
                USERBOT.API_ID,
                USERBOT.API_HASH,
                connection=ConnectionTcpAbridged,
                use_ipv6=False,
                timeout=30,
            )
            await client.connect()
            result = await client.send_code_request(phone)

            self._pending[phone] = {
                "client": client,
                "hash": result.phone_code_hash,
            }

            logger.info(f"📨 Kod yuborildi: {phone}")
            return {"ok": True, "phone": phone}
        except Exception as e:
            logger.error(f"send_code: {e}")
            return {"ok": False, "error": str(e)}

    async def verify_code(self, phone: str, code: str) -> dict:
        """
        2-qadam: Kodni tasdiqlash.
        Agar 2FA bo'lsa, need_2fa=True qaytaradi.
        """
        try:
            phone = phone.strip()
            if not phone.startswith("+"):
                phone = "+" + phone

            p = self._pending.get(phone)
            if not p:
                return {"ok": False, "error": "Avval kod yuboring"}

            client = p["client"]
            code = code.strip().replace(" ", "")

            try:
                await client.sign_in(phone, code, phone_code_hash=p["hash"])
            except SessionPasswordNeededError:
                logger.info(f"🔐 2FA kerak: {phone}")
                return {"ok": True, "need_2fa": True}
            except PhoneCodeInvalidError:
                return {"ok": False, "error": "Kod xato"}
            except PhoneCodeExpiredError:
                return {"ok": False, "error": "Kod muddati tugadi"}

            # Muvaffaqiyat
            session_str = client.session.save()
            await self._save_and_start(session_str, phone)
            return {"ok": True, "need_2fa": False}

        except Exception as e:
            logger.error(f"verify_code: {e}")
            return {"ok": False, "error": str(e)}

    async def verify_2fa(self, phone: str, password: str) -> dict:
        """
        3-qadam (agar 2FA bo'lsa): Parolni tasdiqlash.
        """
        try:
            phone = phone.strip()
            if not phone.startswith("+"):
                phone = "+" + phone

            p = self._pending.get(phone)
            if not p:
                return {"ok": False, "error": "Avval kod yuboring"}

            client = p["client"]
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError:
                return {"ok": False, "error": "Parol xato"}

            session_str = client.session.save()
            await self._save_and_start(session_str, phone)
            return {"ok": True}

        except Exception as e:
            logger.error(f"verify_2fa: {e}")
            return {"ok": False, "error": str(e)}

    async def _save_and_start(self, session_str: str, phone: str):
        """Session ni DB ga saqlash va ulanishni boshlash."""
        # Eski pending ni tozalash
        if phone in self._pending:
            try:
                await self._pending[phone]["client"].disconnect()
            except Exception:
                pass
            del self._pending[phone]

        # Eski client ni to'xtatish
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

        # DB ga saqlash
        if self.db:
            await self.db.save_userbot_session(phone, session_str)
            logger.info(f"💾 Session saqlandi: {phone}")

        # Ulanish
        await self._connect_with_session(session_str)

    async def logout(self) -> dict:
        """Userbot ni o'chirish va DB dan sessiyani tozalash."""
        try:
            if self.client:
                try:
                    await self.client.log_out()
                except Exception:
                    pass
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
                self.client = None

            if self._task:
                self._task.cancel()
                self._task = None

            if self.db:
                await self.db.delete_userbot_session()

            logger.info("🚪 Userbot o'chirildi")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============================================================
    # STATUS
    # ============================================================
    async def get_status(self) -> dict:
        """Hozirgi holatni qaytaradi."""
        try:
            # DB dan ma'lumot
            info = None
            if self.db:
                info = await self.db.get_userbot_info()

            # Hozirgi client holati
            connected = False
            me_info = None
            if self.client:
                try:
                    connected = self.client.is_connected()
                    if connected:
                        me = await self.client.get_me()
                        if me:
                            me_info = {
                                "id": me.id,
                                "username": me.username,
                                "first_name": me.first_name,
                                "phone": me.phone,
                            }
                except Exception:
                    connected = False

            return {
                "ok": True,
                "has_session": bool(info),
                "connected": connected,
                "phone": info.get("phone") if info else None,
                "created_at": info.get("created_at").isoformat() if info and info.get("created_at") else None,
                "me": me_info,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============================================================
    # MESSAGE HANDLER
    # ============================================================
    async def _on_message(self, event):
        try:
            sender = await event.get_sender()
            if not sender:
                return
            sender_username = (getattr(sender, "username", "") or "").lower()
            target = USERBOT.WATCH_BOT_USERNAME.lower()
            if sender_username != target:
                return

            text = event.raw_text or ""
            logger.info(f"📥 CardXabarBot: {text[:120]}")

            parsed = self._parse(text)
            if not parsed:
                logger.warning("⚠️ Parse qilinmadi")
                return

            amount, last4 = parsed
            result = await self.on_payment(amount, last4, text)

            if result and result.get("ok"):
                logger.info(f"✅ Balans qo'shildi: {amount} so'm (karta ***{last4})")
            else:
                logger.info(f"ℹ️ Moslik yo'q: {amount} / ***{last4} → {result}")

        except Exception as e:
            logger.error(f"❌ Handler xato: {e}", exc_info=True)

    @staticmethod
    def _parse(text: str) -> Optional[tuple]:
        if not text:
            return None

        text_low = text.lower()

        is_income = (
            "perevod na kartu" in text_low
            or "popolnenie" in text_low
            or re.search(r"^\s*\+\s*[\d\s.,]+", text, re.MULTILINE)
        )
        if "spisanie" in text_low or "снятие" in text_low:
            return None
        if not is_income:
            return None

        amount = None
        m = re.search(r"[+\-]?\s*([\d]{1,3}(?:[\s,]\d{3})*(?:\.\d{1,2})?)\s*(UZS|so'm|сум)",
                      text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(" ", "").replace(",", "")
            try:
                amount = int(float(raw))
            except ValueError:
                pass

        if amount is None or amount <= 0:
            return None

        last4 = None
        m2 = re.search(r"\*{2,}(\d{4})\b", text)
        if m2:
            last4 = m2.group(1)
        else:
            m3 = re.search(r"(?:karta|card|карта)[^\d]{0,10}(\d{4})\b", text, re.IGNORECASE)
            if m3:
                last4 = m3.group(1)

        if not last4:
            return None

        return amount, last4

    async def stop(self):
        self._stopped = True
        # Pending authlarni yopish
        for phone, p in list(self._pending.items()):
            try:
                await p["client"].disconnect()
            except Exception:
                pass
        self._pending.clear()

        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
