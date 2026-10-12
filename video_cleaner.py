"""
Har soatda ishlaydi:
1. Muddati o'tgan topup_requests larni EXPIRED qiladi
2. Admin kunlari o'tgan R2 videolarni o'chiradi (R2 + DB)
3. Kanal postlar Telegram'da QOLADI (o'chirilmaydi)
"""
import asyncio
import logging
from datetime import datetime

from config import BOT, LIMITS, R2

logger = logging.getLogger("Cleaner")


class VideoCleaner:
    def __init__(self, db, bot):
        self.db = db
        self.bot = bot
        self._task = None
        self._running = False
        self._r2_client = None

    # ============================================================
    # R2 CLIENT (lazy init)
    # ============================================================
    def _get_r2(self):
        if self._r2_client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig

                if not R2.ENDPOINT or not R2.ACCESS_KEY or not R2.SECRET_KEY:
                    logger.warning("R2 sozlamalari to'liq emas — video o'chirish ishlamaydi")
                    return None

                self._r2_client = boto3.client(
                    "s3",
                    endpoint_url=R2.ENDPOINT,
                    aws_access_key_id=R2.ACCESS_KEY,
                    aws_secret_access_key=R2.SECRET_KEY,
                    config=BotoConfig(
                        signature_version="s3v4",
                        retries={"max_attempts": 3, "mode": "standard"},
                    ),
                    region_name="auto",
                )
            except Exception as e:
                logger.error(f"R2 client xato: {e}")
                return None
        return self._r2_client

    # ============================================================
    # START / STOP
    # ============================================================
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

    # ============================================================
    # LOOP
    # ============================================================
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

        # 2. Muddati o'tgan R2 videolar
        try:
            expired = await self.db.get_expired_ads()
            logger.info(f"📹 O'chirilishi kerak: {len(expired)} ta e'lon")

            if not expired:
                logger.info("✅ O'chiriladigan video yo'q")
                return

            r2 = self._get_r2()
            count = 0
            r2_deleted = 0

            for ad in expired:
                ad_id = ad["id"]
                r2_key = ad.get("r2_key")

                # R2'dan o'chirish (faqat r2_key bo'lsa)
                if r2_key and r2:
                    try:
                        r2.delete_object(Bucket=R2.BUCKET, Key=r2_key)
                        r2_deleted += 1
                        logger.info(f"🗑️ R2 o'chirildi: {r2_key}")
                    except Exception as e:
                        logger.error(f"R2 delete xato (ad #{ad_id}, key={r2_key}): {e}")

                # DB'dan EXPIRED qilish + video metadata o'chirish
                try:
                    await self.db.expire_ad(ad_id)
                    count += 1
                    logger.info(f"🗑️ E'lon #{ad_id} → EXPIRED")
                except Exception as e:
                    logger.error(f"expire_ad xato (ad #{ad_id}): {e}")

            logger.info(
                f"✅ {count} ta e'lon EXPIRED qilindi, "
                f"{r2_deleted} ta R2 video o'chirildi"
            )
        except Exception as e:
            logger.error(f"expire ads xato: {e}", exc_info=True)
