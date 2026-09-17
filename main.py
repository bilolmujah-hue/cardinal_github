"""
CARDINAL REKLAMA BOT - Main Entry
==================================
Ishga tushirish: python main.py
"""

import asyncio
import logging
import sys

from bot import Database, CardinalBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("cardinal_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("Main")


async def main():
    db = Database()
    try:
        await db.connect()
        await db.create_tables()
    except Exception as e:
        logger.error(f"❌ Database xatosi: {e}")
        logger.error("💡 pgAdmin ishlayaptimi? Parolni tekshiring!")
        return

    bot = CardinalBot(db)
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("⏹️ To'xtatilmoqda...")
    finally:
        await bot.stop()
        await db.close()
        logger.info("✅ To'xtatildi")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ To'xtatildi")