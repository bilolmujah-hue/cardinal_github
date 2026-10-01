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

        self.client = TelegramClient(
            StringSession(USERBOT.SESSION_STRING),
            USERBOT.API_ID,
            USERBOT.API_HASH,
            device_model="Cardinal",
            system_version="1.0",
            app_version="5.1",
            connection=ConnectionTcpAbridged,     # 🔥 MUHIM
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

        # 🔥 Retry loop bilan ulanish
        while not self._stopped:
            try:
                await self.client.start()
                me = await self.client.get_me()
                logger.info(f"✅ Userbot ishga tushdi: @{me.username or me.id}")
                break
            except Exception as e:
                logger.error(f"❌ Userbot ulanish xatosi: {e}")
                logger.info("⏳ 10 soniyadan keyin qayta urinib ko'riladi...")
                await asyncio.sleep(10)

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

        # Faqat kirim
        is_income = (
            "perevod na kartu" in text_low
            or "popolnenie" in text_low
            or re.search(r"^\s*\+\s*[\d\s.,]+", text, re.MULTILINE)
        )
        if "spisanie" in text_low or "снятие" in text_low:
            return None
        if not is_income:
            return None

        # Amount
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

        # Oxirgi 4 raqam
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
    async with TelegramClient(StringSession(), USERBOT.API_ID, USERBOT.API_HASH) as client:
        s = client.session.save()
        print("\n✅ SESSION_STRING:")
        print(s)
        print("\nRailway da .env ga qo'ying: USERBOT_SESSION=<shu string>")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(generate_session())
