"""
@CardXabarBot dan keladigan to'lov xabarlarini o'qib, avtomatik balans qo'shadi.
"""
import asyncio
import logging
import re
from typing import Optional, Callable, Awaitable

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpAbridged
from telethon.errors import AuthKeyNotFound, AuthKeyDuplicatedError, SessionRevokedError

from config import USERBOT

logger = logging.getLogger("Userbot")


class CardXabarWatcher:
    def __init__(self, on_payment: Callable[[int, str, str], Awaitable[dict]]):
        self.on_payment = on_payment
        self.client: Optional[TelegramClient] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start(self):
        if not USERBOT.SESSION_STRING:
            logger.warning("⚠️ USERBOT_SESSION yo'q — userbot ishga tushmaydi")
            return

        # Session stringni tozalash (probel, yangi qator)
        session_clean = USERBOT.SESSION_STRING.strip().replace("\n", "").replace(" ", "").replace("\r", "")

        if len(session_clean) < 100:
            logger.error("❌ USERBOT_SESSION juda qisqa — noto'g'ri paste qilingan")
            return

        logger.info(f"🔑 Session uzunligi: {len(session_clean)} belgi")

        self.client = TelegramClient(
            StringSession(session_clean),
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

        # 🔥 Retry loop — faqat tarmoq xatolari uchun
        attempt = 0
        max_attempts = 3

        while not self._stopped and attempt < max_attempts:
            attempt += 1
            try:
                await self.client.start()
                me = await self.client.get_me()
                logger.info(f"✅ Userbot ishga tushdi: @{me.username or me.id} (ID: {me.id})")
                break

            except (AuthKeyNotFound, AuthKeyDuplicatedError, SessionRevokedError) as e:
                # 🔥 BU DOIMIY XATO — qayta urinish befoyda
                logger.error("")
                logger.error("=" * 60)
                logger.error("❌ USERBOT_SESSION YAROQSIZ!")
                logger.error("=" * 60)
                logger.error(f"Xato turi: {type(e).__name__}")
                logger.error("")
                logger.error("SABAB:")
                logger.error("  1. Session string buzuq (paste xato)")
                logger.error("  2. Session bekor qilingan (boshqa joyda ishlatilgan)")
                logger.error("  3. API_ID yoki API_HASH noto'g'ri")
                logger.error("")
                logger.error("YECHIM:")
                logger.error("  1. PyCharm ni BUTUNLAY yop")
                logger.error("  2. python userbot.py — yangi session ol")
                logger.error("  3. Railway → Variables → USERBOT_SESSION → yangi string")
                logger.error("  4. Railway → Restart")
                logger.error("=" * 60)
                logger.error("")
                return  # ⛔ To'xtatamiz — qayta urinish befoyda

            except Exception as e:
                logger.error(f"❌ Userbot ulanish xatosi (urinish {attempt}/{max_attempts}): {e}")
                if attempt < max_attempts:
                    logger.info("⏳ 30 soniyadan keyin qayta urinib ko'riladi...")
                    await asyncio.sleep(30)
                else:
                    logger.error("❌ Barcha urinishlar tugadi. Userbot ishga tushmadi.")
                    return

        if self._stopped:
            return

        self._task = asyncio.create_task(self.client.run_until_disconnected())

    async def stop(self):
        self._stopped = True
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass

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


# ============================================================
# SESSION STRING GENERATOR
# ============================================================
async def generate_session():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    print("=== SESSION STRING GENERATOR ===")
    print(f"API_ID: {USERBOT.API_ID}")
    print(f"API_HASH: {USERBOT.API_HASH[:10]}...")
    print("")
    print("Telefon raqamingiz: +998XXXXXXXXX")
    async with TelegramClient(StringSession(), USERBOT.API_ID, USERBOT.API_HASH) as client:
        s = client.session.save()
        print("")
        print("✅ SESSION_STRING:")
        print("=" * 60)
        print(s)
        print("=" * 60)
        print("")
        print(f"Uzunligi: {len(s)} belgi")
        print("")
        print("Railway → Variables → USERBOT_SESSION → shu stringni paste qiling")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(generate_session())
