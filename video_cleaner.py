"""
VideoCleaner v8.0 — Telegram Channel
Har soatda:
1. Muddati o'tgan topup_requests larni EXPIRED qiladi
2. Admin kunlari o'tgan reklamalarni EXPIRED qiladi
3. Video metadata DB'dan o'chiriladi
   (Telegram'dagi video @reklama_db kanalida qoladi — user xohlagan)
"""
import asyncio
import logging
from datetime import datetime

from config import BOT, LIMITS, VIDEO

logger = logging.getLogger("Cleaner")


class VideoCleaner:
    def __init__(self, db, bot):
        self.db = db
        self.bot = bot
        self._task = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("✅ VideoCleaner ishga tushdi (har soatda)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        # Startda darhol, keyin har soatda
        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"❌ Cleaner xato: {e}", exc_info=True)
            await asyncio.sleep(3600)  # 1 soat

    async def run_once(self):
        logger.info("🧹 Cleaner boshlandi...")

        # 1. Muddati o'tgan topuplar
        try:
            await self.db.expire_old_topups()
        except Exception as e:
            logger.error(f"topup expire xato: {e}")

        # 2. Muddati o'tgan reklamalar
        try:
            expired = await self.db.get_expired_ads()
            logger.info(f"📹 O'chirilishi kerak: {len(expired)} ta e'lon")

            if not expired:
                logger.info("✅ O'chiriladigan video yo'q")
                return

            count = 0
            for ad in expired:
                ad_id = ad["id"]
                try:
                    # expire_ad — DB'dan video metadata o'chiradi,
                    # status EXPIRED qiladi. Telegram kanaldagi video qoladi.
                    await self.db.expire_ad(ad_id)
                    count += 1
                    logger.info(f"🗑️ E'lon #{ad_id} → EXPIRED")
                except Exception as e:
                    logger.error(f"expire_ad xato (ad #{ad_id}): {e}")

            logger.info(f"✅ {count} ta e'lon EXPIRED qilindi")

        except Exception as e:
            logger.error(f"expire ads xato: {e}", exc_info=True)
