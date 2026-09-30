"""
Har soatda ishlaydi:
1. Muddati o'tgan topup_requests larni EXPIRED qiladi
2. 7 kundan oshgan e'lonlar videosini Telegram kanaldan o'chirib, DB dan tozalaydi
"""
import asyncio
import logging
from datetime import datetime

from config import BOT, LIMITS

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

        # 2. Muddati o'tgan videolar
        try:
            expired = await self.db.get_expired_ads()
            logger.info(f"📹 O'chirilishi kerak: {len(expired)} ta e'lon")

            for ad in expired:
                ad_id = ad["id"]
                video_fid = ad.get("video_file_id")
                tariff = ad.get("tariff", 1)

                # 1, 3, 4-tarif → video faqat web app'da. 2-chi → kanal ham.
                # Lekin kanalga chiqqan e'lon umuman o'chmaydi (user talab qildi).
                # Faqat web app dagi videoni o'chiramiz.
                # Ya'ni:
                #  - 1-tarif: web app dan o'chadi (video ham)
                #  - 2-tarif: kanalda qoladi, web app dan o'chadi
                #  - 3,4-tarif: kanalda qoladi, web app dan o'chadi
                # Demak hammasida web app dan o'chiriladi (video fayl kanaldan o'chmaydi)

                # Agar video kanalda saqlangan bo'lsa, o'chirmaymiz
                # (kelajak uchun). Faqat DB dagi video_file_id ni NULL qilamiz.
                await self.db.expire_ad(ad_id)
                logger.info(f"🗑️ E'lon #{ad_id} → EXPIRED (video web app dan o'chdi)")

            logger.info(f"✅ {len(expired)} ta e'lon EXPIRED qilindi")
        except Exception as e:
            logger.error(f"expire ads xato: {e}", exc_info=True)