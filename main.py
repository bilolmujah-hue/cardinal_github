import asyncio
import logging
from db import Database
from bot import CardinalBot
from api import API

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("Main")


async def main():
    db = Database()
    await db.connect()
    await db.create_tables()

    bot_app = CardinalBot(db)
    api = API(db, bot_app)

    # API ni background'da ishga tushirish
    await api.start()

    try:
        await bot_app.start()
    finally:
        await bot_app.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())