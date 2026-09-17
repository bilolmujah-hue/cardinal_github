"""
CARDINAL REKLAMA BOT - MUKAMMAL VERSIYA
=========================================
2 ta class:
    1. Database    - PostgreSQL (pgAdmin) bilan ishlash
    2. CardinalBot - Telegram bot + API + Kanal boshqaruvi + Admin panel

Barcha sozlamalar shu faylning tepasida (SOZLAMA class'ida).
"""

import asyncio
import asyncpg
import logging
import json
import base64
import os  # ← SHU QATORNI QO'SHISH KERAK
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from aiohttp import web
import aiohttp_cors

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    CallbackQuery, BufferedInputFile
)

# ============================================================
# SOZLAMALAR
# ============================================================
class SOZLAMA:
    # ===== TELEGRAM =====
    BOT_TOKEN = "8894813624:AAFCo3nDE19T8A2Ql_-W2j4-XemU4G1QcxI"
    WEB_APP_URL = "https://ishbilol1230-dev.github.io/budilnik-app/uzbekcats.html"

    # ===== KANAL =====
    CHANNEL_USERNAME = "@tajriva2"
    CHANNEL_ID = -1001234567890  # ← O'Z KANAL ID'INGIZNI YOZING

     # ===== ADMIN =====
    ADMIN_CHAT_ID = 7038296036
    ADMIN_NAME = "CARDINAL ADMIN"
    ADMIN_CARD = "8600 1234 5678 9012"

    # ===== POSTGRESQL (Railway muhitidan o'qiydi) =====
    DB_HOST = os.getenv("PGHOST", "localhost")
    DB_PORT = int(os.getenv("PGPORT", 5432))
    DB_NAME = os.getenv("PGDATABASE", "cardinal_db")
    DB_USER = os.getenv("PGUSER", "postgres")
    DB_PASSWORD = os.getenv("PGPASSWORD", "root")  # ← O'Z PAROLINGIZNI YOZING

    # ===== API =====
    API_HOST = "0.0.0.0"
    API_PORT = 8080

    # ===== TARIFLAR =====
    TARIFFS = {
        1: {"price": 19000, "days": 1, "type": "STANDARD", "channel": True,  "webapp": False, "name": "Kanal"},
        2: {"price": 9000,  "days": 3, "type": "STANDARD", "channel": False, "webapp": True,  "name": "Web App"},
        3: {"price": 25000, "days": 7, "type": "RARE",     "channel": True,  "webapp": True,  "name": "Web App + Kanal"},
        4: {"price": 29000, "days": 7, "type": "PREMIUM",  "channel": True,  "webapp": True,  "name": "VIP"},
    }

    # ===== LOGO =====
    LOGO_URL = "https://i.ibb.co/cardinal-logo.png"  # ← LOGO RASM URL (ixtiyoriy)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("Cardinal")


# ============================================================
# 1-CLASS: DATABASE
# ============================================================
class Database:
    """PostgreSQL bilan ishlash uchun class"""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    # ---------- ULANISH ----------
    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(
                host=SOZLAMA.DB_HOST, port=SOZLAMA.DB_PORT,
                database=SOZLAMA.DB_NAME, user=SOZLAMA.DB_USER,
                password=SOZLAMA.DB_PASSWORD,
                min_size=1, max_size=10,
            )
            logger.info("✅ PostgreSQL ga ulandi")
        except Exception as e:
            logger.error(f"❌ Database xatosi: {e}")
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("🔌 Database uzildi")

    # ---------- JADVALLAR YARATISH ----------
    async def create_tables(self):
        async with self.pool.acquire() as conn:
            # USERS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              SERIAL PRIMARY KEY,
                    telegram_id     BIGINT UNIQUE NOT NULL,
                    username        VARCHAR(255),
                    first_name      VARCHAR(255),
                    last_name       VARCHAR(255),
                    phone           VARCHAR(20),
                    language_code   VARCHAR(10),
                    balance         BIGINT DEFAULT 0,
                    spent           BIGINT DEFAULT 0,
                    avatar          TEXT,
                    is_admin        BOOLEAN DEFAULT FALSE,
                    is_blocked      BOOLEAN DEFAULT FALSE,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)

            # ADS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ads (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title           VARCHAR(255) NOT NULL,
                    description     TEXT,
                    image_url       TEXT,
                    video_url       TEXT,
                    ad_type         VARCHAR(50) DEFAULT 'STANDARD',
                    price           BIGINT NOT NULL,
                    location        VARCHAR(100),
                    account_data    JSONB,
                    tariff          INTEGER,
                    status          VARCHAR(20) DEFAULT 'PENDING',
                    views           INTEGER DEFAULT 0,
                    likes           INTEGER DEFAULT 0,
                    dislikes        INTEGER DEFAULT 0,
                    reject_reason   TEXT,
                    channel_msg_id  BIGINT,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    expires_at      TIMESTAMP,
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)

            # AD_REACTIONS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_reactions (
                    id              SERIAL PRIMARY KEY,
                    ad_id           INTEGER REFERENCES ads(id) ON DELETE CASCADE,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    reaction        VARCHAR(10) NOT NULL,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    UNIQUE(ad_id, user_id)
                );
            """)

            # CHATS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id              SERIAL PRIMARY KEY,
                    ad_id           INTEGER REFERENCES ads(id) ON DELETE CASCADE,
                    seller_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    buyer_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    UNIQUE(ad_id, buyer_id)
                );
            """)

            # MESSAGES
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              SERIAL PRIMARY KEY,
                    chat_id         INTEGER REFERENCES chats(id) ON DELETE CASCADE,
                    user_id         INTEGER REFERENCES users(id),
                    text            TEXT NOT NULL,
                    is_admin        BOOLEAN DEFAULT FALSE,
                    is_edited       BOOLEAN DEFAULT FALSE,
                    is_deleted      BOOLEAN DEFAULT FALSE,
                    created_at      TIMESTAMP DEFAULT NOW()
                );
            """)

            # TRANSACTIONS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount          BIGINT NOT NULL,
                    type            VARCHAR(20) NOT NULL,
                    description     TEXT,
                    receipt_url     TEXT,
                    status          VARCHAR(20) DEFAULT 'PENDING',
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)

            # BLOCKED_USERS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked_users (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    reason          TEXT,
                    blocked_by      INTEGER,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id)
                );
            """)

            # BROADCASTS
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id              SERIAL PRIMARY KEY,
                    admin_id        INTEGER REFERENCES users(id),
                    message         TEXT,
                    sent_count      INTEGER DEFAULT 0,
                    created_at      TIMESTAMP DEFAULT NOW()
                );
            """)

            logger.info("✅ Barcha jadvallar tayyor")

    # ============================================================
    # USERS
    # ============================================================
    async def get_or_create_user(self, telegram_id, username=None,
                                 first_name=None, last_name=None,
                                 language_code=None) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                is_admin = (telegram_id == SOZLAMA.ADMIN_CHAT_ID)
                user = await conn.fetchrow("""
                    INSERT INTO users (telegram_id, username, first_name, last_name,
                                       language_code, is_admin)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                """, telegram_id, username, first_name, last_name, language_code, is_admin)
                logger.info(f"🆕 Yangi user: {telegram_id}")
            else:
                # Is_admin tekshirish
                if telegram_id == SOZLAMA.ADMIN_CHAT_ID and not user["is_admin"]:
                    await conn.execute(
                        "UPDATE users SET is_admin=TRUE WHERE telegram_id=$1",
                        telegram_id
                    )
                await conn.execute("""
                    UPDATE users SET username=$1, first_name=$2, last_name=$3, updated_at=NOW()
                    WHERE telegram_id=$4
                """, username, first_name, last_name, telegram_id)
            return dict(user)

    async def update_phone(self, telegram_id: int, phone: str) -> bool:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET phone=$1, updated_at=NOW() WHERE telegram_id=$2",
                phone, telegram_id
            )
            return True

    async def get_user(self, telegram_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id=$1", telegram_id
            )
            return dict(user) if user else None

    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
            return dict(user) if user else None

    async def update_user_profile(self, telegram_id: int, first_name=None,
                                  last_name=None, avatar=None) -> bool:
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users
                SET first_name = COALESCE($1, first_name),
                    last_name  = COALESCE($2, last_name),
                    avatar     = COALESCE($3, avatar),
                    updated_at = NOW()
                WHERE telegram_id = $4
            """, first_name, last_name, avatar, telegram_id)
            return True

    async def is_user_blocked(self, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT is_blocked FROM users WHERE telegram_id=$1", telegram_id
            )
            return bool(user and user["is_blocked"])

    async def block_user(self, telegram_id: int, reason: str = None, blocked_by: int = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_blocked=TRUE WHERE telegram_id=$1", telegram_id
            )
            user = await self.get_user(telegram_id)
            if user:
                await conn.execute("""
                    INSERT INTO blocked_users (user_id, reason, blocked_by)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE SET reason=$2, blocked_by=$3
                """, user["id"], reason, blocked_by)

    async def unblock_user(self, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_blocked=FALSE WHERE telegram_id=$1", telegram_id
            )
            user = await self.get_user(telegram_id)
            if user:
                await conn.execute(
                    "DELETE FROM blocked_users WHERE user_id=$1", user["id"]
                )
            return True

    async def get_all_users(self, limit: int = 100) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]

    async def get_blocked_users(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.*, b.reason, b.created_at as blocked_at
                FROM blocked_users b
                JOIN users u ON u.id = b.user_id
                ORDER BY b.created_at DESC
            """)
            return [dict(r) for r in rows]

    # ============================================================
    # BALANCE
    # ============================================================
    async def update_balance(self, telegram_id: int, amount: int, tx_type: str = "topup",
                             receipt_url: str = None):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if tx_type == "topup":
                    await conn.execute("""
                        UPDATE users SET balance = balance + $1, updated_at=NOW()
                        WHERE telegram_id = $2
                    """, amount, telegram_id)
                elif tx_type == "spend":
                    await conn.execute("""
                        UPDATE users
                        SET balance = balance - $1, spent = spent + $1, updated_at=NOW()
                        WHERE telegram_id = $2
                    """, amount, telegram_id)

                user = await self.get_user(telegram_id)
                if user:
                    await conn.execute("""
                        INSERT INTO transactions (user_id, amount, type, description,
                                                   receipt_url, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, user["id"], amount, tx_type, f"Balance {tx_type}",
                        receipt_url,
                        "APPROVED" if (tx_type == "topup" and not receipt_url) else "PENDING")

    async def create_topup_request(self, telegram_id: int, amount: int, receipt_url: str) -> int:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return None
            tx_id = await conn.fetchval("""
                INSERT INTO transactions (user_id, amount, type, description,
                                          receipt_url, status)
                VALUES ($1, $2, 'topup', $3, $4, 'PENDING')
                RETURNING id
            """, user["id"], amount, "Topup request", receipt_url)
            return tx_id

    async def approve_topup(self, tx_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                tx = await conn.fetchrow("SELECT * FROM transactions WHERE id=$1", tx_id)
                if not tx or tx["status"] != "PENDING":
                    return False

                await conn.execute("""
                    UPDATE transactions SET status='APPROVED', updated_at=NOW() WHERE id=$1
                """, tx_id)

                user = await self.get_user_by_id(tx["user_id"])
                if user:
                    await conn.execute("""
                        UPDATE users SET balance = balance + $1, updated_at=NOW()
                        WHERE id = $2
                    """, tx["amount"], user["id"])
            return True

    async def reject_topup(self, tx_id: int, reason: str = None) -> bool:
        async with self.pool.acquire() as conn:
            tx = await conn.fetchrow("SELECT * FROM transactions WHERE id=$1", tx_id)
            if not tx or tx["status"] != "PENDING":
                return False
            await conn.execute("""
                UPDATE transactions SET status='REJECTED', description=$1, updated_at=NOW()
                WHERE id=$2
            """, reason or "Rad etildi", tx_id)
            return True

    async def get_pending_topups(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT t.*, u.telegram_id, u.first_name, u.last_name, u.phone
                FROM transactions t
                JOIN users u ON u.id = t.user_id
                WHERE t.status='PENDING' AND t.type='topup'
                ORDER BY t.created_at DESC
            """)
            return [dict(r) for r in rows]

    async def get_user_transactions(self, telegram_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return []
            rows = await conn.fetch("""
                SELECT * FROM transactions WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50
            """, user["id"])
            return [dict(r) for r in rows]

    # ============================================================
    # ADS
    # ============================================================
    async def create_ad(self, user_id: int, data: Dict) -> int:
        async with self.pool.acquire() as conn:
            ad_id = await conn.fetchval("""
                INSERT INTO ads (
                    user_id, title, description, image_url, video_url,
                    ad_type, price, location, account_data, tariff,
                    status, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING id
            """,
                user_id, data.get("title"), data.get("description"),
                data.get("image_url"), data.get("video_url"),
                data.get("ad_type", "STANDARD"), data.get("price", 0),
                data.get("location"), json.dumps(data.get("account_data", {})),
                data.get("tariff"), "PENDING", data.get("expires_at"),
            )
            return ad_id

    async def get_active_ads(self, category: str = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            query = """
                SELECT ads.*, users.first_name, users.last_name
                FROM ads JOIN users ON users.id = ads.user_id
                WHERE ads.status='ACTIVE'
                  AND (ads.expires_at IS NULL OR ads.expires_at > NOW())
            """
            if category and category != "ALL":
                query += f" AND ads.ad_type='{category}'"
            query += """
                ORDER BY CASE ads.ad_type
                    WHEN 'PREMIUM' THEN 1 WHEN 'RARE' THEN 2 ELSE 3 END,
                    ads.created_at DESC
            """
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_all_ads(self, status: str = None) -> List[Dict]:
        """Admin uchun barcha reklamalar"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT ads.*, users.first_name, users.last_name, users.telegram_id as seller_tg
                FROM ads JOIN users ON users.id = ads.user_id
            """
            if status:
                query += f" WHERE ads.status='{status}'"
            query += " ORDER BY ads.created_at DESC LIMIT 200"
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_ad_by_id(self, ad_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            ad = await conn.fetchrow("""
                SELECT ads.*, users.first_name as seller_first_name,
                       users.last_name as seller_last_name,
                       users.telegram_id as seller_telegram_id
                FROM ads JOIN users ON users.id = ads.user_id
                WHERE ads.id = $1
            """, ad_id)
            return dict(ad) if ad else None

    async def get_user_ads(self, telegram_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ads.* FROM ads JOIN users ON users.id = ads.user_id
                WHERE users.telegram_id = $1 ORDER BY ads.created_at DESC
            """, telegram_id)
            return [dict(r) for r in rows]

    async def get_pending_ads(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ads.*, users.telegram_id, users.first_name, users.last_name, users.phone
                FROM ads JOIN users ON users.id = ads.user_id
                WHERE ads.status='PENDING' ORDER BY ads.created_at DESC
            """)
            return [dict(r) for r in rows]

    async def update_ad_status(self, ad_id: int, status: str, reason: str = None,
                                channel_msg_id: int = None):
        async with self.pool.acquire() as conn:
            if channel_msg_id:
                await conn.execute("""
                    UPDATE ads SET status=$1, reject_reason=$2, channel_msg_id=$3, updated_at=NOW()
                    WHERE id=$4
                """, status, reason, channel_msg_id, ad_id)
            else:
                await conn.execute("""
                    UPDATE ads SET status=$1, reject_reason=$2, updated_at=NOW()
                    WHERE id=$3
                """, status, reason, ad_id)

    async def delete_ad(self, ad_id: int) -> bool:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM ads WHERE id=$1", ad_id)
            return True

    async def increment_ad_views(self, ad_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE ads SET views=views+1 WHERE id=$1", ad_id)

    async def react_to_ad(self, ad_id: int, telegram_id: int, reaction: str) -> Dict:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return {"ok": False}

            old = await conn.fetchrow("""
                SELECT * FROM ad_reactions WHERE ad_id=$1 AND user_id=$2
            """, ad_id, user["id"])

            if old:
                if old["reaction"] == reaction:
                    await conn.execute("DELETE FROM ad_reactions WHERE id=$1", old["id"])
                    col = "likes" if reaction == "like" else "dislikes"
                    await conn.execute(f"UPDATE ads SET {col}={col}-1 WHERE id=$1", ad_id)
                else:
                    await conn.execute(
                        "UPDATE ad_reactions SET reaction=$1 WHERE id=$2",
                        reaction, old["id"]
                    )
                    old_col = "likes" if old["reaction"] == "like" else "dislikes"
                    new_col = "likes" if reaction == "like" else "dislikes"
                    await conn.execute(f"""
                        UPDATE ads SET {old_col}={old_col}-1, {new_col}={new_col}+1 WHERE id=$1
                    """, ad_id)
            else:
                await conn.execute("""
                    INSERT INTO ad_reactions (ad_id, user_id, reaction)
                    VALUES ($1, $2, $3)
                """, ad_id, user["id"], reaction)
                col = "likes" if reaction == "like" else "dislikes"
                await conn.execute(f"UPDATE ads SET {col}={col}+1 WHERE id=$1", ad_id)

            ad = await self.get_ad_by_id(ad_id)
            return {"ok": True, "likes": ad["likes"], "dislikes": ad["dislikes"]}

    # ============================================================
    # CHATS
    # ============================================================
    async def get_or_create_chat(self, ad_id: int, buyer_telegram_id: int) -> int:
        async with self.pool.acquire() as conn:
            ad = await self.get_ad_by_id(ad_id)
            if not ad:
                return None

            buyer = await self.get_user(buyer_telegram_id)
            if not buyer:
                return None

            seller = await self.get_user_by_id(ad["user_id"])
            if not seller:
                return None

            # O'ziga chat ochmasin
            if seller["telegram_id"] == buyer_telegram_id:
                return None

            chat = await conn.fetchrow("""
                SELECT * FROM chats WHERE ad_id=$1 AND buyer_id=$2
            """, ad_id, buyer["id"])

            if not chat:
                chat_id = await conn.fetchval("""
                    INSERT INTO chats (ad_id, seller_id, buyer_id)
                    VALUES ($1, $2, $3) RETURNING id
                """, ad_id, seller["id"], buyer["id"])
                return chat_id
            return chat["id"]

    async def get_user_chats(self, telegram_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return []

            rows = await conn.fetch("""
                SELECT c.*, a.title as ad_title, a.image_url as ad_image, a.price as ad_price,
                       s.first_name as seller_name, s.telegram_id as seller_tg,
                       b.first_name as buyer_name, b.telegram_id as buyer_tg,
                       (SELECT text FROM messages WHERE chat_id=c.id AND is_deleted=FALSE
                        ORDER BY created_at DESC LIMIT 1) as last_message,
                       (SELECT created_at FROM messages WHERE chat_id=c.id AND is_deleted=FALSE
                        ORDER BY created_at DESC LIMIT 1) as last_time
                FROM chats c
                JOIN ads a ON a.id = c.ad_id
                JOIN users s ON s.id = c.seller_id
                JOIN users b ON b.id = c.buyer_id
                WHERE c.seller_id=$1 OR c.buyer_id=$1
                ORDER BY c.created_at DESC
            """, user["id"])
            return [dict(r) for r in rows]

    async def get_all_chats_admin(self) -> List[Dict]:
        """Admin uchun barcha chatlar"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT c.id, c.ad_id, c.created_at,
                       a.title as ad_title, a.image_url as ad_image, a.price as ad_price,
                       s.first_name as seller_name, s.telegram_id as seller_tg,
                       s.id as seller_id,
                       b.first_name as buyer_name, b.telegram_id as buyer_tg,
                       b.id as buyer_id,
                       (SELECT text FROM messages WHERE chat_id=c.id AND is_deleted=FALSE
                        ORDER BY created_at DESC LIMIT 1) as last_message,
                       (SELECT created_at FROM messages WHERE chat_id=c.id AND is_deleted=FALSE
                        ORDER BY created_at DESC LIMIT 1) as last_time,
                       (SELECT COUNT(*) FROM messages WHERE chat_id=c.id AND is_deleted=FALSE) as msg_count
                FROM chats c
                JOIN ads a ON a.id = c.ad_id
                JOIN users s ON s.id = c.seller_id
                JOIN users b ON b.id = c.buyer_id
                ORDER BY c.created_at DESC
            """)
            return [dict(r) for r in rows]

    async def get_chat_messages(self, chat_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT m.*, u.first_name, u.last_name, u.telegram_id, u.is_admin as user_is_admin,
                       u.is_blocked as user_is_blocked
                FROM messages m
                JOIN users u ON u.id = m.user_id
                WHERE m.chat_id=$1 AND m.is_deleted=FALSE
                ORDER BY m.created_at ASC
            """, chat_id)
            return [dict(r) for r in rows]

    async def send_message(self, chat_id: int, telegram_id: int, text: str) -> int:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return None
            msg_id = await conn.fetchval("""
                INSERT INTO messages (chat_id, user_id, text, is_admin)
                VALUES ($1, $2, $3, $4) RETURNING id
            """, chat_id, user["id"], text, user["is_admin"])
            return msg_id

    async def edit_message(self, msg_id: int, text: str, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return False
            msg = await conn.fetchrow("SELECT * FROM messages WHERE id=$1", msg_id)
            if not msg:
                return False
            if msg["user_id"] != user["id"] and not user["is_admin"]:
                return False
            await conn.execute("""
                UPDATE messages SET text=$1, is_edited=TRUE WHERE id=$2
            """, text, msg_id)
            return True

    async def delete_message(self, msg_id: int, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            user = await self.get_user(telegram_id)
            if not user:
                return False
            msg = await conn.fetchrow("SELECT * FROM messages WHERE id=$1", msg_id)
            if not msg:
                return False
            if msg["user_id"] != user["id"] and not user["is_admin"]:
                return False
            await conn.execute(
                "UPDATE messages SET is_deleted=TRUE WHERE id=$1", msg_id
            )
            return True

    async def get_chat_by_id(self, chat_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT c.*, a.title as ad_title, a.image_url as ad_image, a.price as ad_price,
                       s.telegram_id as seller_tg, s.first_name as seller_name,
                       b.telegram_id as buyer_tg, b.first_name as buyer_name
                FROM chats c
                JOIN ads a ON a.id = c.ad_id
                JOIN users s ON s.id = c.seller_id
                JOIN users b ON b.id = c.buyer_id
                WHERE c.id=$1
            """, chat_id)
            return dict(row) if row else None

    # ============================================================
    # BROADCAST
    # ============================================================
    async def get_all_user_ids(self) -> List[int]:
        """Barcha foydalanuvchi telegram_id lari"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT telegram_id FROM users WHERE is_blocked=FALSE")
            return [r["telegram_id"] for r in rows]

    async def save_broadcast(self, admin_id: int, message: str, sent_count: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO broadcasts (admin_id, message, sent_count)
                VALUES ($1, $2, $3)
            """, admin_id, message, sent_count)

    # ============================================================
    # STATS
    # ============================================================
    async def get_stats(self) -> Dict:
        async with self.pool.acquire() as conn:
            try:
                pending_topups = await conn.fetchval(
                    "SELECT COUNT(*) FROM transactions WHERE status='PENDING'"
                )
            except Exception:
                pending_topups = 0

            return {
                "users": await conn.fetchval("SELECT COUNT(*) FROM users"),
                "blocked": await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked=TRUE"),
                "ads": await conn.fetchval("SELECT COUNT(*) FROM ads"),
                "active_ads": await conn.fetchval("SELECT COUNT(*) FROM ads WHERE status='ACTIVE'"),
                "pending": await conn.fetchval("SELECT COUNT(*) FROM ads WHERE status='PENDING'"),
                "pending_topups": pending_topups,
                "chats": await conn.fetchval("SELECT COUNT(*) FROM chats"),
                "total_balance": await conn.fetchval("SELECT COALESCE(SUM(balance),0) FROM users"),
                "total_spent": await conn.fetchval("SELECT COALESCE(SUM(spent),0) FROM users"),
            }


# ============================================================
# 2-CLASS: CARDINAL BOT
# ============================================================
class CardinalBot:
    """Telegram bot + API + Kanal + Admin panel"""

    def __init__(self, db: Database):
        self.bot = Bot(token=SOZLAMA.BOT_TOKEN)
        self.dp = Dispatcher()
        self.db = db
        self.api_app = web.Application()
        self._register_handlers()
        self._setup_api_routes()

    # ---------- HANDLERLAR ----------
    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, CommandStart())
        self.dp.message.register(self.cmd_admin, Command("admin"))
        self.dp.message.register(self.cmd_channelid, Command("channelid"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.handle_contact, F.contact)
        self.dp.message.register(self.handle_webapp_data, F.web_app_data)
        self.dp.message.register(self.handle_other, F.text)

    # ---------- /start ----------
    async def cmd_start(self, message: Message):
        user = message.from_user

        if await self.db.is_user_blocked(user.id):
            await message.answer("🚫 Siz botdan bloklangansiz!")
            return

        await self.db.get_or_create_user(
            telegram_id=user.id, username=user.username,
            first_name=user.first_name, last_name=user.last_name,
            language_code=user.language_code,
        )

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )

        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "🎮 <b>CARDINAL REKLAMA</b> botiga xush kelibsiz!\n\n"
            "PUBG Mobile akkauntlaringizni sotish uchun reklama bering.\n\n"
            "Botdan foydalanish uchun telefon raqamingizni yuboring.",
            parse_mode="HTML", reply_markup=keyboard,
        )

    # ---------- /admin ----------
    async def cmd_admin(self, message: Message):
        if message.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
            await message.answer("❌ Siz admin emassiz!")
            return

        stats = await self.db.get_stats()
        await message.answer(
            f"🛡️ <b>ADMIN PANEL</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n"
            f"🚫 Bloklangan: <b>{stats['blocked']}</b>\n"
            f"📢 Reklamalar: <b>{stats['ads']}</b> (faol: {stats['active_ads']})\n"
            f"⏳ Reklama kutilmoqda: <b>{stats['pending']}</b>\n"
            f"💳 Chek kutilmoqda: <b>{stats['pending_topups']}</b>\n"
            f"💬 Chatlar: <b>{stats['chats']}</b>\n"
            f"💵 Umumiy balans: <b>{stats['total_balance']:,} so'm</b>\n\n"
            f"🌐 <b>Admin panel Web App'da:</b>\n{SOZLAMA.WEB_APP_URL}",
            parse_mode="HTML",
        )

    # ---------- /channelid ----------
    async def cmd_channelid(self, message: Message):
        await message.answer(
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"Type: {message.chat.type}\n"
            f"Title: {message.chat.title or 'N/A'}",
            parse_mode="HTML"
        )

    # ---------- /stats ----------
    async def cmd_stats(self, message: Message):
        if message.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
            return
        stats = await self.db.get_stats()
        await message.answer(f"📊 {json.dumps(stats, indent=2, default=str)}")

    # ---------- KONTAKT ----------
    async def handle_contact(self, message: Message):
        contact = message.contact
        phone = contact.phone_number.replace("+", "").replace(" ", "")
        if phone.startswith("998"):
            phone = phone[3:]

        user = message.from_user
        await self.db.get_or_create_user(
            telegram_id=user.id, username=user.username,
            first_name=user.first_name, last_name=user.last_name,
        )
        await self.db.update_phone(user.id, phone)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🌐 Web App ni ochish",
                    web_app=WebAppInfo(url=SOZLAMA.WEB_APP_URL)
                )],
                [InlineKeyboardButton(
                    text="📢 Kanalimiz",
                    url=f"https://t.me/{SOZLAMA.CHANNEL_USERNAME.replace('@', '')}"
                )],
            ]
        )

        is_admin = (user.id == SOZLAMA.ADMIN_CHAT_ID)
        admin_text = "\n\n🛡️ <b>Siz ADMINSIZ!</b> Profilingizda Admin panel tugmasi bor." if is_admin else ""

        await message.answer(
            "✅ <b>Telefon raqamingiz qabul qilindi!</b>\n\n"
            "🎮 Endi Web App'ga kirishingiz mumkin." + admin_text,
            parse_mode="HTML", reply_markup=keyboard,
        )

    # ---------- WEB APP DATA ----------
    async def handle_webapp_data(self, message: Message):
        try:
            data = json.loads(message.web_app_data.data)
            action = data.get("action")
            logger.info(f"📨 WebApp action: {action}")

            if action == "update_profile":
                await self.db.update_user_profile(
                    telegram_id=message.from_user.id,
                    first_name=data.get("first_name"),
                    last_name=data.get("last_name"),
                    avatar=data.get("avatar"),
                )
                await message.answer("✅ Profil yangilandi!")

            elif action == "create_ad":
                await self._handle_create_ad(message, data)

        except Exception as e:
            logger.error(f"❌ WebApp data error: {e}")

    async def _handle_create_ad(self, message: Message, data: dict):
        user = await self.db.get_user(message.from_user.id)
        if not user:
            await message.answer("❌ /start bosing")
            return

        ad_data = data.get("ad_data", {})
        tariff_id = int(ad_data.get("tariff", 1))
        tariff = SOZLAMA.TARIFFS.get(tariff_id, SOZLAMA.TARIFFS[1])

        if user["balance"] < tariff["price"]:
            await message.answer(f"❌ Balans yetarli emas. Kerak: {tariff['price']:,}")
            return

        expires_at = datetime.now() + timedelta(days=tariff["days"])
        ad_id = await self.db.create_ad(user["id"], {
            "title": ad_data.get("title"),
            "description": ad_data.get("description"),
            "image_url": ad_data.get("image_url"),
            "video_url": ad_data.get("video_url"),
            "ad_type": tariff["type"],
            "price": ad_data.get("price"),
            "location": ad_data.get("location"),
            "account_data": ad_data.get("account_data"),
            "tariff": tariff_id,
            "expires_at": expires_at,
        })

        await self.db.update_balance(message.from_user.id, tariff["price"], "spend")

        ad = await self.db.get_ad_by_id(ad_id)
        await self._send_ad_to_admin(ad)

        await message.answer(
            f"✅ Reklama yuborildi! ID: <code>{ad_id}</code>\n"
            f"⏳ Admin tasdiqlashini kuting.",
            parse_mode="HTML",
        )

    async def _send_ad_to_admin(self, ad: dict):
        try:
            text = (
                f"🆕 <b>YANGI REKLAMA</b>\n\n"
                f"📝 <b>{ad['title']}</b>\n"
                f"💰 {ad['price']:,} so'm\n"
                f"📍 {ad.get('location', '-')}\n"
                f"🎯 Tarif: {ad.get('tariff')}\n"
                f"🆔 ID: <code>{ad['id']}</code>\n\n"
                f"Tasdiqlaysizmi?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_ad_{ad['id']}"),
                    InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_ad_{ad['id']}")
                ]]
            )

            if ad.get("video_url"):
                await self.bot.send_video(
                    SOZLAMA.ADMIN_CHAT_ID, ad["video_url"],
                    caption=text, parse_mode="HTML", reply_markup=keyboard
                )
            elif ad.get("image_url"):
                # Base64 yoki URL
                if ad["image_url"].startswith("data:image"):
                    header, encoded = ad["image_url"].split(",", 1)
                    img_bytes = base64.b64decode(encoded)
                    photo = BufferedInputFile(img_bytes, filename="ad.jpg")
                    await self.bot.send_photo(
                        SOZLAMA.ADMIN_CHAT_ID, photo,
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
                else:
                    await self.bot.send_photo(
                        SOZLAMA.ADMIN_CHAT_ID, ad["image_url"],
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
            else:
                await self.bot.send_message(
                    SOZLAMA.ADMIN_CHAT_ID, text,
                    parse_mode="HTML", reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Admin'ga yuborishda xato: {e}")

    # ---------- CALLBACK'LAR ----------
    async def _setup_callbacks(self):
        @self.dp.callback_query(F.data.startswith("approve_ad_"))
        async def approve_cb(cb: CallbackQuery):
            if cb.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return

            ad_id = int(cb.data.replace("approve_ad_", ""))
            ad = await self.db.get_ad_by_id(ad_id)

            await self.db.update_ad_status(ad_id, "ACTIVE")

            tariff = SOZLAMA.TARIFFS.get(ad.get("tariff", 1))
            if tariff and tariff["channel"]:
                await self._post_to_channel(ad)

            try:
                await self.bot.send_message(
                    ad["seller_telegram_id"],
                    f"✅ Sizning reklamangiz tasdiqlandi!\n\n"
                    f"📢 {ad['title']}\n🆔 ID: <code>{ad_id}</code>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.answer("✅ Tasdiqlandi!")
            await cb.message.answer(f"✅ Reklama #{ad_id} tasdiqlandi va joylashtirildi")

        @self.dp.callback_query(F.data.startswith("reject_ad_"))
        async def reject_cb(cb: CallbackQuery):
            if cb.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return

            ad_id = int(cb.data.replace("reject_ad_", ""))
            ad = await self.db.get_ad_by_id(ad_id)

            await self.db.update_ad_status(ad_id, "REJECTED", "Admin rad etdi")

            tariff = SOZLAMA.TARIFFS.get(ad.get("tariff", 1))
            if tariff:
                await self.db.update_balance(ad["seller_telegram_id"], tariff["price"], "topup")

            try:
                await self.bot.send_message(
                    ad["seller_telegram_id"],
                    f"❌ Reklamangiz rad etildi. Pul qaytarildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.answer("❌ Rad etildi")
            await cb.message.answer(f"❌ Reklama #{ad_id} rad etildi")

        @self.dp.callback_query(F.data.startswith("approve_topup_"))
        async def approve_topup_cb(cb: CallbackQuery):
            if cb.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return

            tx_id = int(cb.data.replace("approve_topup_", ""))
            ok = await self.db.approve_topup(tx_id)

            if ok:
                tx = await self.db.pool.fetchrow("SELECT * FROM transactions WHERE id=$1", tx_id)
                if tx:
                    user = await self.db.get_user_by_id(tx["user_id"])
                    if user:
                        try:
                            await self.bot.send_message(
                                user["telegram_id"],
                                f"✅ Balansingiz <b>{tx['amount']:,} so'm</b>ga to'ldirildi!",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.answer("✅ Tasdiqlandi!" if ok else "❌ Xatolik")
            await cb.message.answer(f"{'✅' if ok else '❌'} Chek #{tx_id} {'tasdiqlandi' if ok else 'xato'}")

        @self.dp.callback_query(F.data.startswith("reject_topup_"))
        async def reject_topup_cb(cb: CallbackQuery):
            if cb.from_user.id != SOZLAMA.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return

            tx_id = int(cb.data.replace("reject_topup_", ""))
            ok = await self.db.reject_topup(tx_id, "Admin rad etdi")

            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.answer("❌ Rad etildi" if ok else "Xatolik")

    async def _post_to_channel(self, ad: dict):
        try:
            base_url = SOZLAMA.WEB_APP_URL
            buy_url = f"{base_url}?open=ad&ad_id={ad['id']}"
            sell_url = f"{base_url}?open=create"

            text = (
                f"🔥 <b>{ad['title']}</b>\n\n"
                f"{ad.get('description', '')}\n\n"
                f"💰 <b>{ad['price']:,} so'm</b>\n"
                f"📍 {ad.get('location', '-')}\n\n"
                f"📲 Batafsil ma'lumot uchun Web App'ga kiring"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 Akkount sotib olish", url=buy_url)],
                    [InlineKeyboardButton(text="📢 Reklama bermoqchiman", url=sell_url)],
                ]
            )

            if ad.get("video_url"):
                msg = await self.bot.send_video(
                    SOZLAMA.CHANNEL_ID, ad["video_url"],
                    caption=text, parse_mode="HTML", reply_markup=keyboard
                )
            elif ad.get("image_url"):
                if ad["image_url"].startswith("data:image"):
                    header, encoded = ad["image_url"].split(",", 1)
                    img_bytes = base64.b64decode(encoded)
                    photo = BufferedInputFile(img_bytes, filename="ad.jpg")
                    msg = await self.bot.send_photo(
                        SOZLAMA.CHANNEL_ID, photo,
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
                else:
                    msg = await self.bot.send_photo(
                        SOZLAMA.CHANNEL_ID, ad["image_url"],
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
            else:
                msg = await self.bot.send_message(
                    SOZLAMA.CHANNEL_ID, text,
                    parse_mode="HTML", reply_markup=keyboard
                )

            await self.db.update_ad_status(ad["id"], "ACTIVE", channel_msg_id=msg.message_id)
            logger.info(f"📢 Kanalga joylandi: #{ad['id']}")
        except Exception as e:
            logger.error(f"Kanalga joylashda xato: {e}")

    async def handle_other(self, message: Message):
        if message.from_user.id == SOZLAMA.ADMIN_CHAT_ID:
            # Admin uchun buyruqlar
            await message.answer(
                "🛡️ Admin buyruqlar:\n"
                "/admin - statistika\n"
                "/stats - batafsil\n"
                "/channelid - kanal ID\n\n"
                f"🌐 Web App: {SOZLAMA.WEB_APP_URL}"
            )
        else:
            await message.answer("🎮 /start bosing")

    # ============================================================
    # API ROUTES
    # ============================================================
    def _setup_api_routes(self):
        cors = aiohttp_cors.setup(self.api_app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True, expose_headers="*",
                allow_headers="*", allow_methods="*",
            )
        })

        routes = [
            # Asosiy
            self.api_app.router.add_get("/", self.api_index),
            self.api_app.router.add_get("/api/stats", self.api_stats),

            # User
            self.api_app.router.add_get("/api/user/{telegram_id}", self.api_get_user),
            self.api_app.router.add_post("/api/update-profile", self.api_update_profile),
            self.api_app.router.add_get("/api/user-transactions/{telegram_id}", self.api_user_transactions),

            # Ads
            self.api_app.router.add_get("/api/ads", self.api_get_ads),
            self.api_app.router.add_get("/api/ad/{ad_id}", self.api_get_ad),
            self.api_app.router.add_get("/api/my-ads/{telegram_id}", self.api_get_my_ads),
            self.api_app.router.add_post("/api/create-ad", self.api_create_ad),
            self.api_app.router.add_post("/api/react-ad", self.api_react_ad),

            # Balance
            self.api_app.router.add_post("/api/topup", self.api_topup),
            self.api_app.router.add_post("/api/topup-receipt", self.api_topup_receipt),

            # Chats
            self.api_app.router.add_get("/api/chats/{telegram_id}", self.api_get_chats),
            self.api_app.router.add_get("/api/chat/{chat_id}", self.api_get_chat),
            self.api_app.router.add_post("/api/chat/start", self.api_start_chat),
            self.api_app.router.add_post("/api/chat/send", self.api_send_message),
            self.api_app.router.add_post("/api/chat/edit", self.api_edit_message),
            self.api_app.router.add_post("/api/chat/delete", self.api_delete_message),
            self.api_app.router.add_post("/api/chat/block", self.api_block_user),

            # Admin
            self.api_app.router.add_get("/api/admin/pending-ads", self.api_pending_ads),
            self.api_app.router.add_get("/api/admin/pending-topups", self.api_pending_topups),
            self.api_app.router.add_get("/api/admin/chats", self.api_admin_chats),
            self.api_app.router.add_get("/api/admin/users", self.api_admin_users),
            self.api_app.router.add_get("/api/admin/blocked", self.api_admin_blocked),
            self.api_app.router.add_get("/api/admin/all-ads", self.api_admin_all_ads),
            self.api_app.router.add_post("/api/admin/approve-ad", self.api_approve_ad),
            self.api_app.router.add_post("/api/admin/reject-ad", self.api_reject_ad),
            self.api_app.router.add_post("/api/admin/delete-ad", self.api_admin_delete_ad),
            self.api_app.router.add_post("/api/admin/approve-topup", self.api_approve_topup),
            self.api_app.router.add_post("/api/admin/reject-topup", self.api_reject_topup),
            self.api_app.router.add_post("/api/admin/unblock-user", self.api_admin_unblock),
            self.api_app.router.add_post("/api/admin/broadcast", self.api_admin_broadcast),
        ]

        for route in routes:
            cors.add(route)

    def _check_admin(self, telegram_id: int) -> bool:
        return telegram_id == SOZLAMA.ADMIN_CHAT_ID

    # ---------- ASOSIY API ----------
    async def api_index(self, request):
        return web.json_response({
            "app": "Cardinal API",
            "version": "2.0",
            "status": "running"
        })

    async def api_stats(self, request):
        return web.json_response(await self.db.get_stats())

    # ---------- USER ----------
    async def api_get_user(self, request):
        tg_id = int(request.match_info["telegram_id"])
        user = await self.db.get_user(tg_id)
        if not user:
            return web.json_response({"error": "Topilmadi"}, status=404)
        for k, v in user.items():
            if isinstance(v, datetime): user[k] = v.isoformat()
        # Admin faqat shu ID uchun
        user["is_admin"] = self._check_admin(tg_id)
        return web.json_response(user)

    async def api_update_profile(self, request):
        try:
            data = await request.json()
            await self.db.update_user_profile(
                telegram_id=int(data["telegram_id"]),
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                avatar=data.get("avatar"),
            )
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_user_transactions(self, request):
        tg_id = int(request.match_info["telegram_id"])
        txs = await self.db.get_user_transactions(tg_id)
        for t in txs:
            for k, v in t.items():
                if isinstance(v, datetime): t[k] = v.isoformat()
        return web.json_response(txs)

    # ---------- ADS ----------
    async def api_get_ads(self, request):
        ads = await self.db.get_active_ads()
        for ad in ads:
            for k, v in ad.items():
                if isinstance(v, datetime): ad[k] = v.isoformat()
            if isinstance(ad.get("account_data"), str):
                try:
                    ad["account_data"] = json.loads(ad["account_data"])
                except:
                    ad["account_data"] = {}
        return web.json_response(ads)

    async def api_get_ad(self, request):
        ad_id = int(request.match_info["ad_id"])
        ad = await self.db.get_ad_by_id(ad_id)
        if not ad:
            return web.json_response({"error": "Topilmadi"}, status=404)
        for k, v in ad.items():
            if isinstance(v, datetime): ad[k] = v.isoformat()
        if isinstance(ad.get("account_data"), str):
            try:
                ad["account_data"] = json.loads(ad["account_data"])
            except:
                ad["account_data"] = {}
        await self.db.increment_ad_views(ad_id)
        return web.json_response(ad)

    async def api_get_my_ads(self, request):
        tg_id = int(request.match_info["telegram_id"])
        ads = await self.db.get_user_ads(tg_id)
        for ad in ads:
            for k, v in ad.items():
                if isinstance(v, datetime): ad[k] = v.isoformat()
            if isinstance(ad.get("account_data"), str):
                try:
                    ad["account_data"] = json.loads(ad["account_data"])
                except:
                    ad["account_data"] = {}
        return web.json_response(ads)

    async def api_create_ad(self, request):
        try:
            data = await request.json()
            tg_id = int(data["telegram_id"])
            user = await self.db.get_user(tg_id)
            if not user:
                return web.json_response({"error": "User topilmadi"}, status=404)

            ad_data = data.get("ad_data", {})
            tariff_id = int(ad_data.get("tariff", 1))
            tariff = SOZLAMA.TARIFFS.get(tariff_id, SOZLAMA.TARIFFS[1])

            if user["balance"] < tariff["price"]:
                return web.json_response({
                    "error": "Balans yetarli emas",
                    "need": tariff["price"],
                    "have": user["balance"]
                }, status=400)

            expires_at = datetime.now() + timedelta(days=tariff["days"])
            ad_id = await self.db.create_ad(user["id"], {
                "title": ad_data.get("title"),
                "description": ad_data.get("description"),
                "image_url": ad_data.get("image_url"),
                "video_url": ad_data.get("video_url"),
                "ad_type": tariff["type"],
                "price": ad_data.get("price"),
                "location": ad_data.get("location"),
                "account_data": ad_data.get("account_data"),
                "tariff": tariff_id,
                "expires_at": expires_at,
            })

            await self.db.update_balance(tg_id, tariff["price"], "spend")

            ad = await self.db.get_ad_by_id(ad_id)
            await self._send_ad_to_admin(ad)

            return web.json_response({"ok": True, "ad_id": ad_id, "paid": tariff["price"]})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_react_ad(self, request):
        try:
            data = await request.json()
            result = await self.db.react_to_ad(
                int(data["ad_id"]), int(data["telegram_id"]), data["reaction"]
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------- BALANCE ----------
    async def api_topup(self, request):
        try:
            data = await request.json()
            tg_id = int(data["telegram_id"])
            amount = int(data["amount"])
            if amount < 1000:
                return web.json_response({"error": "Min 1000"}, status=400)
            await self.db.update_balance(tg_id, amount, "topup")
            user = await self.db.get_user(tg_id)
            return web.json_response({"ok": True, "new_balance": user["balance"]})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_topup_receipt(self, request):
        try:
            data = await request.json()
            tg_id = int(data["telegram_id"])
            amount = int(data["amount"])
            receipt = data.get("receipt_url")

            if not receipt:
                return web.json_response({"error": "Chek kerak"}, status=400)

            tx_id = await self.db.create_topup_request(tg_id, amount, receipt)

            user = await self.db.get_user(tg_id)
            try:
                text = (
                    f"💳 <b>YANGI TO'LOV SO'ROVI</b>\n\n"
                    f"👤 {user['first_name']} {user['last_name'] or ''}\n"
                    f"📱 +998{user['phone']}\n"
                    f"💰 {amount:,} so'm\n"
                    f"🆔 TX: <code>{tx_id}</code>"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_topup_{tx_id}"),
                    InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_topup_{tx_id}"),
                ]])

                if receipt.startswith("data:image"):
                    header, encoded = receipt.split(",", 1)
                    img_bytes = base64.b64decode(encoded)
                    photo = BufferedInputFile(img_bytes, filename="receipt.jpg")
                    await self.bot.send_photo(
                        SOZLAMA.ADMIN_CHAT_ID, photo,
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
                else:
                    await self.bot.send_photo(
                        SOZLAMA.ADMIN_CHAT_ID, receipt,
                        caption=text, parse_mode="HTML", reply_markup=keyboard
                    )
            except Exception as e:
                logger.error(f"Admin'ga chek yuborishda xato: {e}")

            return web.json_response({"ok": True, "tx_id": tx_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------- CHAT ----------
    async def api_get_chats(self, request):
        tg_id = int(request.match_info["telegram_id"])
        chats = await self.db.get_user_chats(tg_id)
        for c in chats:
            for k, v in c.items():
                if isinstance(v, datetime): c[k] = v.isoformat()
        return web.json_response(chats)

    async def api_get_chat(self, request):
        chat_id = int(request.match_info["chat_id"])
        chat = await self.db.get_chat_by_id(chat_id)
        if not chat:
            return web.json_response({"error": "Topilmadi"}, status=404)
        msgs = await self.db.get_chat_messages(chat_id)
        for m in msgs:
            for k, v in m.items():
                if isinstance(v, datetime): m[k] = v.isoformat()
        for k, v in chat.items():
            if isinstance(v, datetime): chat[k] = v.isoformat()
        return web.json_response({"chat": chat, "messages": msgs})

    async def api_start_chat(self, request):
        try:
            data = await request.json()
            chat_id = await self.db.get_or_create_chat(
                int(data["ad_id"]), int(data["telegram_id"])
            )
            if not chat_id:
                return web.json_response({"error": "Chat yaratilmadi"}, status=400)

            chat = await self.db.get_chat_by_id(chat_id)
            buyer = await self.db.get_user(int(data["telegram_id"]))
            ad = await self.db.get_ad_by_id(int(data["ad_id"]))

            notify = (
                f"🆕 <b>Yangi chat</b>\n\n"
                f"📢 {ad['title']}\n"
                f"👤 Xaridor: {buyer['first_name']}"
            )
            for tg_id in [chat["seller_tg"], SOZLAMA.ADMIN_CHAT_ID]:
                if tg_id != int(data["telegram_id"]):
                    try:
                        await self.bot.send_message(tg_id, notify, parse_mode="HTML")
                    except Exception:
                        pass

            return web.json_response({"ok": True, "chat_id": chat_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_send_message(self, request):
        try:
            data = await request.json()
            msg_id = await self.db.send_message(
                int(data["chat_id"]), int(data["telegram_id"]), data["text"]
            )
            if not msg_id:
                return web.json_response({"error": "Xabar yuborilmadi"}, status=400)

            chat = await self.db.get_chat_by_id(int(data["chat_id"]))
            sender = await self.db.get_user(int(data["telegram_id"]))
            sender_name = f"{sender['first_name'] or ''} {sender['last_name'] or ''}".strip()

            for tg_id in [chat["seller_tg"], chat["buyer_tg"]]:
                if tg_id != int(data["telegram_id"]):
                    try:
                        await self.bot.send_message(
                            tg_id,
                            f"💬 <b>{chat['ad_title']}</b>\n\n"
                            f"👤 {sender_name}: {data['text'][:200]}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

            return web.json_response({"ok": True, "msg_id": msg_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_edit_message(self, request):
        try:
            data = await request.json()
            ok = await self.db.edit_message(
                int(data["msg_id"]), data["text"], int(data["telegram_id"])
            )
            return web.json_response({"ok": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_delete_message(self, request):
        try:
            data = await request.json()
            ok = await self.db.delete_message(
                int(data["msg_id"]), int(data["telegram_id"])
            )
            return web.json_response({"ok": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_block_user(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            await self.db.block_user(
                int(data["user_telegram_id"]),
                data.get("reason"),
                SOZLAMA.ADMIN_CHAT_ID
            )

            try:
                await self.bot.send_message(
                    int(data["user_telegram_id"]),
                    "🚫 Siz botdan bloklandingiz!",
                )
            except Exception:
                pass

            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------- ADMIN ----------
    async def api_pending_ads(self, request):
        ads = await self.db.get_pending_ads()
        for ad in ads:
            for k, v in ad.items():
                if isinstance(v, datetime): ad[k] = v.isoformat()
            if isinstance(ad.get("account_data"), str):
                try:
                    ad["account_data"] = json.loads(ad["account_data"])
                except:
                    ad["account_data"] = {}
        return web.json_response(ads)

    async def api_pending_topups(self, request):
        txs = await self.db.get_pending_topups()
        for t in txs:
            for k, v in t.items():
                if isinstance(v, datetime): t[k] = v.isoformat()
        return web.json_response(txs)

    async def api_admin_chats(self, request):
        chats = await self.db.get_all_chats_admin()
        for c in chats:
            for k, v in c.items():
                if isinstance(v, datetime): c[k] = v.isoformat()
        return web.json_response(chats)

    async def api_admin_users(self, request):
        users = await self.db.get_all_users(200)
        for u in users:
            for k, v in u.items():
                if isinstance(v, datetime): u[k] = v.isoformat()
            u["is_admin"] = self._check_admin(u["telegram_id"])
        return web.json_response(users)

    async def api_admin_blocked(self, request):
        users = await self.db.get_blocked_users()
        for u in users:
            for k, v in u.items():
                if isinstance(v, datetime): u[k] = v.isoformat()
        return web.json_response(users)

    async def api_admin_all_ads(self, request):
        ads = await self.db.get_all_ads()
        for ad in ads:
            for k, v in ad.items():
                if isinstance(v, datetime): ad[k] = v.isoformat()
            if isinstance(ad.get("account_data"), str):
                try:
                    ad["account_data"] = json.loads(ad["account_data"])
                except:
                    ad["account_data"] = {}
        return web.json_response(ads)

    async def api_approve_ad(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            ad_id = int(data["ad_id"])
            ad = await self.db.get_ad_by_id(ad_id)

            await self.db.update_ad_status(ad_id, "ACTIVE")

            tariff = SOZLAMA.TARIFFS.get(ad.get("tariff", 1))
            if tariff and tariff["channel"]:
                await self._post_to_channel(ad)

            try:
                await self.bot.send_message(
                    ad["seller_telegram_id"],
                    f"✅ Reklamangiz tasdiqlandi!",
                )
            except Exception:
                pass

            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_reject_ad(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            ad_id = int(data["ad_id"])
            reason = data.get("reason", "Admin rad etdi")
            ad = await self.db.get_ad_by_id(ad_id)

            await self.db.update_ad_status(ad_id, "REJECTED", reason)

            tariff = SOZLAMA.TARIFFS.get(ad.get("tariff", 1))
            if tariff:
                await self.db.update_balance(ad["seller_telegram_id"], tariff["price"], "topup")

            try:
                await self.bot.send_message(
                    ad["seller_telegram_id"],
                    f"❌ Reklamangiz rad etildi.\nSabab: {reason}\nPul qaytarildi.",
                )
            except Exception:
                pass

            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_admin_delete_ad(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            ad_id = int(data["ad_id"])
            await self.db.delete_ad(ad_id)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_approve_topup(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            tx_id = int(data["tx_id"])
            ok = await self.db.approve_topup(tx_id)

            if ok:
                tx = await self.db.pool.fetchrow("SELECT * FROM transactions WHERE id=$1", tx_id)
                if tx:
                    user = await self.db.get_user_by_id(tx["user_id"])
                    if user:
                        try:
                            await self.bot.send_message(
                                user["telegram_id"],
                                f"✅ Balansingiz <b>{tx['amount']:,} so'm</b>ga to'ldirildi!",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

            return web.json_response({"ok": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_reject_topup(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            tx_id = int(data["tx_id"])
            ok = await self.db.reject_topup(tx_id, data.get("reason"))
            return web.json_response({"ok": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_admin_unblock(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            await self.db.unblock_user(int(data["user_telegram_id"]))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def api_admin_broadcast(self, request):
        try:
            data = await request.json()
            if not self._check_admin(int(data["admin_telegram_id"])):
                return web.json_response({"error": "Ruxsat yo'q"}, status=403)

            message_text = data.get("message", "").strip()
            if not message_text:
                return web.json_response({"error": "Xabar bo'sh"}, status=400)

            user_ids = await self.db.get_all_user_ids()
            sent = 0
            for uid in user_ids:
                if uid == SOZLAMA.ADMIN_CHAT_ID:
                    continue
                try:
                    await self.bot.send_message(uid, message_text, parse_mode="HTML")
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass

            await self.db.save_broadcast(SOZLAMA.ADMIN_CHAT_ID, message_text, sent)
            return web.json_response({"ok": True, "sent": sent, "total": len(user_ids)})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------- ISHGA TUSHIRISH ----------
    async def _start_api(self):
        runner = web.AppRunner(self.api_app)
        await runner.setup()
        site = web.TCPSite(runner, SOZLAMA.API_HOST, SOZLAMA.API_PORT)
        await site.start()
        logger.info(f"🌐 API Server: http://{SOZLAMA.API_HOST}:{SOZLAMA.API_PORT}")

    async def start(self):
        logger.info("🚀 BOT ishga tushdi...")
        await self._setup_callbacks()
        await self._start_api()
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.bot.session.close()
