"""
Cardinal DB v5.6
- Soft delete kartalar uchun
- Karta holder saqlanadi
- Topup holder qaytaradi
"""
import asyncpg
import json
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any
from config import DB, TARIFFS, INITIAL_CARDS, LIMITS

logger = logging.getLogger("DB")


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=DB.HOST, port=DB.PORT, database=DB.NAME,
            user=DB.USER, password=DB.PASSWORD,
            min_size=5, max_size=50,
            command_timeout=60,
        )
        logger.info("✅ PostgreSQL ulandi")

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ============================================================
    # TABLES
    # ============================================================
    async def create_tables(self):
        async with self.pool.acquire() as c:
            # USERS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              SERIAL PRIMARY KEY,
                    telegram_id     BIGINT UNIQUE NOT NULL,
                    username        VARCHAR(255),
                    first_name      VARCHAR(255),
                    last_name       VARCHAR(255),
                    phone           VARCHAR(20),
                    password_hash   VARCHAR(255),
                    balance         BIGINT DEFAULT 0,
                    spent           BIGINT DEFAULT 0,
                    avatar          TEXT,
                    is_registered   BOOLEAN DEFAULT FALSE,
                    is_admin        BOOLEAN DEFAULT FALSE,
                    is_blocked      BOOLEAN DEFAULT FALSE,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # CARDS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    id              SERIAL PRIMARY KEY,
                    number          VARCHAR(20) UNIQUE NOT NULL,
                    holder          VARCHAR(100),
                    is_active       BOOLEAN DEFAULT TRUE,
                    total_received  BIGINT DEFAULT 0,
                    created_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # ADS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS ads (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title           VARCHAR(255) NOT NULL,
                    video_file_id   TEXT,
                    ad_type         VARCHAR(50) DEFAULT 'STANDARD',
                    price           BIGINT NOT NULL,
                    currency        VARCHAR(10) DEFAULT 'UZS',
                    location        VARCHAR(100),
                    full_location   VARCHAR(255),
                    account_data    JSONB DEFAULT '{}'::jsonb,
                    tariff          INTEGER,
                    status          VARCHAR(20) DEFAULT 'PENDING',
                    views           INTEGER DEFAULT 0,
                    reject_reason   TEXT,
                    channel_msg_id  BIGINT,
                    top_until       TIMESTAMP,
                    expires_at      TIMESTAMP,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # SAVED_ADS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS saved_ads (
                    id          SERIAL PRIMARY KEY,
                    ad_id       INTEGER REFERENCES ads(id) ON DELETE CASCADE,
                    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    UNIQUE(ad_id, user_id)
                );
            """)
            # TRANSACTIONS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount          BIGINT NOT NULL,
                    type            VARCHAR(20) NOT NULL,
                    description     TEXT,
                    status          VARCHAR(20) DEFAULT 'PENDING',
                    card_id         INTEGER,
                    card_last4      VARCHAR(4),
                    payer_last4     VARCHAR(4),
                    receipt_file_id TEXT,
                    expires_at      TIMESTAMP,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # TOPUP_REQUESTS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS topup_requests (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount          BIGINT NOT NULL,
                    card_id         INTEGER REFERENCES cards(id) ON DELETE SET NULL,
                    card_number     VARCHAR(20),
                    status          VARCHAR(30) DEFAULT 'WAITING',
                    expires_at      TIMESTAMP NOT NULL,
                    matched_at      TIMESTAMP,
                    receipt_url     TEXT,
                    completed_at    TIMESTAMP,
                    reject_reason   TEXT,
                    created_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # FEEDBACKS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS feedbacks (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    text        TEXT NOT NULL,
                    rating      INTEGER DEFAULT 5,
                    is_visible  BOOLEAN DEFAULT TRUE,
                    created_at  TIMESTAMP DEFAULT NOW()
                );
            """)
            # BLOCKED
            await c.execute("""
                CREATE TABLE IF NOT EXISTS blocked_users (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    reason      TEXT,
                    blocked_by  INTEGER,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id)
                );
            """)
            # BROADCASTS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id          SERIAL PRIMARY KEY,
                    admin_id    INTEGER REFERENCES users(id),
                    message     TEXT,
                    sent_count  INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW()
                );
            """)
            # USERBOT SESSIONS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS userbot_sessions (
                    id              SERIAL PRIMARY KEY,
                    phone           VARCHAR(20) NOT NULL,
                    session_string  TEXT NOT NULL,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)
            # ADMIN CONTACTS
            await c.execute("""
                CREATE TABLE IF NOT EXISTS admin_contacts (
                    id          SERIAL PRIMARY KEY,
                    chat_id     BIGINT UNIQUE NOT NULL,
                    username    VARCHAR(255),
                    first_name  VARCHAR(255),
                    last_name   VARCHAR(255),
                    info        TEXT,
                    is_active   BOOLEAN DEFAULT TRUE,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    updated_at  TIMESTAMP DEFAULT NOW()
                );
            """)

        await self._migrate()

        async with self.pool.acquire() as c:
            await c.execute("CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_ads_expires ON ads(expires_at);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_topup_status ON topup_requests(status);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_topup_amount ON topup_requests(amount, status);")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_admin_active ON admin_contacts(is_active);")

        await self._seed_cards()
        await self._cleanup_base64_videos()
        logger.info("✅ Jadvallar tayyor")

    async def _migrate(self):
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS spent BIGINT DEFAULT 0",
            "ALTER TABLE ads ADD COLUMN IF NOT EXISTS video_file_id TEXT",
            "ALTER TABLE ads ADD COLUMN IF NOT EXISTS top_until TIMESTAMP",
            "ALTER TABLE ads ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'UZS'",
            "ALTER TABLE ads ADD COLUMN IF NOT EXISTS account_data JSONB DEFAULT '{}'::jsonb",
            "ALTER TABLE topup_requests ADD COLUMN IF NOT EXISTS receipt_url TEXT",
            "ALTER TABLE topup_requests ADD COLUMN IF NOT EXISTS matched_at TIMESTAMP",
            "ALTER TABLE topup_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            "ALTER TABLE topup_requests ADD COLUMN IF NOT EXISTS reject_reason TEXT",
            "ALTER TABLE admin_contacts ADD COLUMN IF NOT EXISTS info TEXT",
            "ALTER TABLE admin_contacts ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE cards ADD COLUMN IF NOT EXISTS holder VARCHAR(100) DEFAULT 'CARDINAL ADMIN'",
        ]
        async with self.pool.acquire() as c:
            for sql in migrations:
                try:
                    await c.execute(sql)
                except Exception as e:
                    logger.warning(f"Migration skip: {e}")

    async def _cleanup_base64_videos(self):
        try:
            async with self.pool.acquire() as c:
                await c.execute("UPDATE ads SET video_file_id = NULL WHERE video_file_id LIKE 'data:%'")
                await c.execute("""
                    UPDATE ads SET status='EXPIRED'
                    WHERE video_file_id IS NULL AND status='ACTIVE'
                      AND created_at < NOW() - INTERVAL '1 day'
                """)
        except Exception as e:
            logger.error(f"cleanup: {e}")

    async def _seed_cards(self):
        async with self.pool.acquire() as c:
            for num in INITIAL_CARDS:
                await c.execute("""
                    INSERT INTO cards (number, holder, is_active)
                    VALUES ($1, $2, TRUE)
                    ON CONFLICT (number) DO NOTHING
                """, num, "CARDINAL ADMIN")

    # ============================================================
    # USERBOT SESSION
    # ============================================================
    async def save_userbot_session(self, phone, session_string):
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("DELETE FROM userbot_sessions")
                await c.execute(
                    "INSERT INTO userbot_sessions (phone, session_string, is_active) VALUES ($1, $2, TRUE)",
                    phone, session_string
                )
        return True

    async def get_userbot_session(self):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT session_string FROM userbot_sessions WHERE is_active=TRUE ORDER BY id DESC LIMIT 1")
            return r["session_string"] if r else None

    async def get_userbot_info(self):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT id, phone, is_active, created_at, updated_at FROM userbot_sessions WHERE is_active=TRUE ORDER BY id DESC LIMIT 1")
            return dict(r) if r else None

    async def delete_userbot_session(self):
        async with self.pool.acquire() as c:
            await c.execute("DELETE FROM userbot_sessions")
        return True

    # ============================================================
    # USERS
    # ============================================================
    async def get_or_create_user(self, telegram_id, username=None, first_name=None, last_name=None):
        async with self.pool.acquire() as c:
            u = await c.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
            if not u:
                is_admin = (telegram_id == 7038296036)
                u = await c.fetchrow("""
                    INSERT INTO users (telegram_id, username, first_name, last_name, is_admin)
                    VALUES ($1,$2,$3,$4,$5) RETURNING *
                """, telegram_id, username, first_name, last_name, is_admin)
            else:
                await c.execute(
                    "UPDATE users SET username=$1, first_name=$2, last_name=$3, updated_at=NOW() WHERE telegram_id=$4",
                    username, first_name, last_name, telegram_id
                )
            return dict(u)

    async def get_user(self, telegram_id):
        async with self.pool.acquire() as c:
            u = await c.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
            return dict(u) if u else None

    async def get_user_by_id(self, uid):
        async with self.pool.acquire() as c:
            u = await c.fetchrow("SELECT * FROM users WHERE id=$1", uid)
            return dict(u) if u else None

    async def get_user_full(self, telegram_id):
        async with self.pool.acquire() as c:
            u = await c.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
            if not u:
                return None
            d = dict(u)
            d["ads_count"] = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1", d["id"])
            d["is_admin"] = (telegram_id == 7038296036) or d.get("is_admin", False)
            return d

    async def add_admin(self, telegram_id):
        async with self.pool.acquire() as c:
            r = await c.execute("UPDATE users SET is_admin=TRUE, updated_at=NOW() WHERE telegram_id=$1", telegram_id)
            return r == "UPDATE 1"

    async def update_phone(self, telegram_id, phone):
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE users SET phone=$1, is_registered=TRUE, updated_at=NOW() WHERE telegram_id=$2",
                phone, telegram_id
            )

    async def is_registered(self, telegram_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT is_registered FROM users WHERE telegram_id=$1", telegram_id)
            return bool(r and r["is_registered"])

    async def update_profile(self, telegram_id, first_name=None, last_name=None, avatar=None):
        async with self.pool.acquire() as c:
            await c.execute("""
                UPDATE users SET first_name=COALESCE($1,first_name), last_name=COALESCE($2,last_name),
                    avatar=COALESCE($3,avatar), updated_at=NOW() WHERE telegram_id=$4
            """, first_name, last_name, avatar, telegram_id)

    async def is_blocked(self, telegram_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT is_blocked FROM users WHERE telegram_id=$1", telegram_id)
            return bool(r and r["is_blocked"])

    async def block_user(self, telegram_id, reason=None):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE users SET is_blocked=TRUE WHERE telegram_id=$1", telegram_id)
            u = await self.get_user(telegram_id)
            if u:
                await c.execute("""
                    INSERT INTO blocked_users (user_id, reason) VALUES ($1,$2)
                    ON CONFLICT (user_id) DO UPDATE SET reason=$2
                """, u["id"], reason)

    async def unblock_user(self, telegram_id):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE users SET is_blocked=FALSE WHERE telegram_id=$1", telegram_id)
            u = await self.get_user(telegram_id)
            if u:
                await c.execute("DELETE FROM blocked_users WHERE user_id=$1", u["id"])

    async def get_all_users(self, limit=200):
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM users ORDER BY created_at DESC LIMIT $1", limit)
            return [dict(r) for r in rows]

    async def get_blocked(self):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT u.*, b.reason FROM blocked_users b
                JOIN users u ON u.id=b.user_id ORDER BY b.created_at DESC
            """)
            return [dict(r) for r in rows]

    # ============================================================
    # CARDS
    # ============================================================
    async def get_cards(self, active_only=True):
        async with self.pool.acquire() as c:
            q = "SELECT * FROM cards"
            if active_only:
                q += " WHERE is_active=TRUE"
            q += " ORDER BY id"
            return [dict(r) for r in await c.fetch(q)]

    async def add_card(self, number, holder="CARDINAL ADMIN"):
        async with self.pool.acquire() as c:
            try:
                await c.execute("""
                    INSERT INTO cards (number, holder, is_active)
                    VALUES ($1, $2, TRUE)
                    ON CONFLICT (number) DO UPDATE
                        SET holder = EXCLUDED.holder,
                            is_active = TRUE
                """, number, holder)
                return True
            except Exception as e:
                logger.error(f"add_card: {e}")
                return False

    async def remove_card(self, card_id):
        """Soft delete — foreign key xatolarini oldini oladi."""
        async with self.pool.acquire() as c:
            await c.execute("UPDATE cards SET is_active=FALSE WHERE id=$1", card_id)
            return True

    # ============================================================
    # BALANCE
    # ============================================================
    async def update_balance(self, telegram_id, amount, tx_type="topup", desc=None):
        async with self.pool.acquire() as c:
            async with c.transaction():
                if tx_type == "topup":
                    await c.execute("UPDATE users SET balance=balance+$1, updated_at=NOW() WHERE telegram_id=$2", amount, telegram_id)
                elif tx_type == "spend":
                    await c.execute("UPDATE users SET balance=balance-$1, spent=spent+$1, updated_at=NOW() WHERE telegram_id=$2", amount, telegram_id)
                u = await self.get_user(telegram_id)
                if u:
                    await c.execute("""
                        INSERT INTO transactions (user_id, amount, type, description, status)
                        VALUES ($1,$2,$3,$4,'APPROVED')
                    """, u["id"], amount, tx_type, desc or tx_type)

    async def remove_balance(self, telegram_id, amount):
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE users SET balance=GREATEST(balance-$1,0), updated_at=NOW() WHERE telegram_id=$2", amount, telegram_id)
                u = await self.get_user(telegram_id)
                if u:
                    await c.execute("""
                        INSERT INTO transactions (user_id, amount, type, description, status)
                        VALUES ($1,$2,'remove','Admin olib tashladi','APPROVED')
                    """, u["id"], amount)

    # ============================================================
    # ADS
    # ============================================================
    async def create_ad(self, user_id, data):
        async with self.pool.acquire() as c:
            acc_json = json.dumps(data.get("account_data", {}) or {}, ensure_ascii=False)
            return await c.fetchval("""
                INSERT INTO ads (user_id, title, video_file_id, ad_type, price, currency,
                    location, full_location, account_data, tariff, status, expires_at, top_until)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,'PENDING',$11,$12) RETURNING id
            """, user_id, data["title"], data.get("video_file_id"),
                data.get("ad_type","STANDARD"), data["price"], data.get("currency","UZS"),
                data.get("location"), data.get("full_location"), acc_json,
                data.get("tariff"), data.get("expires_at"), data.get("top_until"))

    def _parse_ad(self, r):
        d = dict(r)
        if isinstance(d.get("account_data"), str):
            try:
                d["account_data"] = json.loads(d["account_data"])
            except Exception:
                d["account_data"] = {}
        elif d.get("account_data") is None:
            d["account_data"] = {}
        for k in ("video_data", "video_base64", "video"):
            d["account_data"].pop(k, None)
        vid = d.get("video_file_id")
        if vid and isinstance(vid, str) and vid.startswith("data:"):
            d["video_file_id"] = None
        return d

    async def get_active_ads(self, category=None):
        async with self.pool.acquire() as c:
            q = """
                SELECT a.id, a.user_id, a.title, a.video_file_id, a.ad_type, a.price,
                       a.currency, a.location, a.full_location, a.account_data, a.tariff,
                       a.status, a.views, a.top_until, a.expires_at, a.created_at,
                       u.first_name, u.last_name, u.telegram_id as seller_tg
                FROM ads a JOIN users u ON u.id=a.user_id
                WHERE a.status='ACTIVE' AND (a.expires_at IS NULL OR a.expires_at > NOW())
                ORDER BY CASE WHEN a.top_until IS NOT NULL AND a.top_until > NOW() THEN 1
                    WHEN a.ad_type='PREMIUM' THEN 2 WHEN a.ad_type='RARE' THEN 3 ELSE 4 END,
                    a.created_at DESC LIMIT 100
            """
            return [self._parse_ad(r) for r in await c.fetch(q)]

    async def get_ad(self, ad_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("""
                SELECT a.*, u.telegram_id as seller_tg, u.first_name as seller_name
                FROM ads a JOIN users u ON u.id=a.user_id WHERE a.id=$1
            """, ad_id)
            return self._parse_ad(r) if r else None

    async def get_user_ads(self, telegram_id):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT a.id, a.user_id, a.title, a.video_file_id, a.ad_type, a.price,
                       a.currency, a.location, a.full_location, a.account_data, a.tariff,
                       a.status, a.views, a.reject_reason, a.top_until, a.expires_at,
                       a.created_at, a.updated_at
                FROM ads a JOIN users u ON u.id=a.user_id
                WHERE u.telegram_id=$1 ORDER BY a.created_at DESC LIMIT 50
            """, telegram_id)
            return [self._parse_ad(r) for r in rows]

    async def get_pending_ads(self):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT a.id, a.user_id, a.title, a.video_file_id, a.ad_type, a.price,
                       a.currency, a.location, a.full_location, a.account_data, a.tariff,
                       a.status, a.views, a.created_at,
                       u.telegram_id, u.first_name, u.last_name, u.phone
                FROM ads a JOIN users u ON u.id=a.user_id
                WHERE a.status='PENDING' ORDER BY a.created_at DESC LIMIT 50
            """)
            return [self._parse_ad(r) for r in rows]

    async def update_ad_status(self, ad_id, status, reason=None, channel_msg_id=None):
        async with self.pool.acquire() as c:
            if channel_msg_id:
                await c.execute(
                    "UPDATE ads SET status=$1, reject_reason=$2, channel_msg_id=$3, updated_at=NOW() WHERE id=$4",
                    status, reason, channel_msg_id, ad_id
                )
            else:
                await c.execute(
                    "UPDATE ads SET status=$1, reject_reason=$2, updated_at=NOW() WHERE id=$3",
                    status, reason, ad_id
                )

    async def delete_ad(self, ad_id):
        async with self.pool.acquire() as c:
            await c.execute("DELETE FROM ads WHERE id=$1", ad_id)

    async def increment_views(self, ad_id):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE ads SET views=views+1 WHERE id=$1", ad_id)

    # ============================================================
    # SAVED
    # ============================================================
    async def toggle_save(self, ad_id, telegram_id):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return {"ok": False}
            ex = await c.fetchrow("SELECT id FROM saved_ads WHERE ad_id=$1 AND user_id=$2", ad_id, u["id"])
            if ex:
                await c.execute("DELETE FROM saved_ads WHERE id=$1", ex["id"])
                return {"ok": True, "saved": False}
            await c.execute("INSERT INTO saved_ads (ad_id, user_id) VALUES ($1,$2)", ad_id, u["id"])
            return {"ok": True, "saved": True}

    async def get_saved(self, telegram_id):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return []
            rows = await c.fetch("""
                SELECT a.id, a.user_id, a.title, a.video_file_id, a.ad_type, a.price,
                       a.currency, a.location, a.full_location, a.account_data, a.tariff,
                       a.status, a.views, a.top_until, a.expires_at, a.created_at
                FROM saved_ads s JOIN ads a ON a.id=s.ad_id
                WHERE s.user_id=$1 AND a.status='ACTIVE'
                  AND (a.expires_at IS NULL OR a.expires_at>NOW())
                ORDER BY s.created_at DESC LIMIT 50
            """, u["id"])
            return [self._parse_ad(r) for r in rows]

    # ============================================================
    # TOPUP
    # ============================================================
    async def create_topup_request(self, telegram_id, amount):
        """10 daqiqalik so'rov. Karta holder bilan qaytariladi."""
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return None

            await c.execute("""
                UPDATE topup_requests SET status='CANCELLED'
                WHERE user_id=$1 AND status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
            """, u["id"])

            card = await c.fetchrow("""
                SELECT * FROM cards
                WHERE is_active=TRUE
                  AND id NOT IN (
                      SELECT card_id FROM topup_requests
                      WHERE amount=$1 AND status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
                        AND expires_at > NOW()
                  )
                ORDER BY RANDOM() LIMIT 1
            """, amount)

            if not card:
                card = await c.fetchrow("SELECT * FROM cards WHERE is_active=TRUE ORDER BY RANDOM() LIMIT 1")
            if not card:
                return None

            expires = datetime.now() + timedelta(minutes=LIMITS.PAYMENT_TIMEOUT_MIN)
            rid = await c.fetchval("""
                INSERT INTO topup_requests (user_id, amount, card_id, card_number, status, expires_at)
                VALUES ($1,$2,$3,$4,'WAITING',$5) RETURNING id
            """, u["id"], amount, card["id"], card["number"], expires)

            return {
                "id": rid,
                "card_number": card["number"],
                "card_holder": card.get("holder") or "CARDINAL ADMIN",
                "expires_at": expires,
            }

    async def get_pending_topup(self, telegram_id):
        """Hozirgi aktiv so'rovni qaytaradi — holder JOIN bilan."""
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return None
            r = await c.fetchrow("""
                SELECT t.*, c.holder AS card_holder
                FROM topup_requests t
                LEFT JOIN cards c ON c.id = t.card_id
                WHERE t.user_id=$1
                  AND t.status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
                  AND t.expires_at > NOW()
                ORDER BY t.created_at DESC LIMIT 1
            """, u["id"])
            return dict(r) if r else None

    async def get_topup_by_id(self, req_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("""
                SELECT t.*, c.holder AS card_holder
                FROM topup_requests t
                LEFT JOIN cards c ON c.id = t.card_id
                WHERE t.id=$1
            """, req_id)
            return dict(r) if r else None

    async def expire_old_topups(self):
        async with self.pool.acquire() as c:
            await c.execute("""
                UPDATE topup_requests SET status='EXPIRED'
                WHERE status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
                  AND expires_at <= NOW()
            """)

    async def match_payment(self, amount, payer_last4):
        """Userbot xabar o'qidi. Silent — xabar yubormaymiz."""
        async with self.pool.acquire() as c:
            req = await c.fetchrow("""
                SELECT * FROM topup_requests
                WHERE amount=$1 AND status='WAITING' AND expires_at > NOW()
                  AND RIGHT(card_number, 4) = $2
                ORDER BY created_at ASC LIMIT 1
            """, amount, payer_last4)

            if not req:
                req = await c.fetchrow("""
                    SELECT * FROM topup_requests
                    WHERE amount=$1 AND status='WAITING' AND expires_at > NOW()
                    ORDER BY created_at ASC LIMIT 1
                """, amount)

            if not req:
                return {"ok": False, "reason": "no_request"}

            await c.execute("""
                UPDATE topup_requests SET status='MATCHED', matched_at=NOW()
                WHERE id=$1
            """, req["id"])

            u = await self.get_user_by_id(req["user_id"])
            return {
                "ok": True,
                "user_tg": u["telegram_id"] if u else 0,
                "amount": amount,
                "request_id": req["id"],
                "silent": True,
            }

    async def submit_receipt(self, telegram_id, receipt_url):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return {"ok": False, "reason": "no_user"}

            req = await c.fetchrow("""
                SELECT * FROM topup_requests
                WHERE user_id=$1 AND status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
                ORDER BY created_at DESC LIMIT 1
            """, u["id"])
            if not req:
                return {"ok": False, "reason": "no_request"}

            await c.execute("UPDATE topup_requests SET receipt_url=$1 WHERE id=$2", receipt_url, req["id"])

            user_info = {
                "user_name": f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                "phone": u.get("phone",""),
                "telegram_id": u["telegram_id"],
                "amount": req["amount"],
                "request_id": req["id"],
            }

            if req["status"] == "MATCHED":
                async with c.transaction():
                    await c.execute("""
                        UPDATE topup_requests SET status='COMPLETED', completed_at=NOW()
                        WHERE id=$1
                    """, req["id"])
                    await c.execute(
                        "UPDATE users SET balance=balance+$1, updated_at=NOW() WHERE id=$2",
                        req["amount"], req["user_id"]
                    )
                    await c.execute("""
                        INSERT INTO transactions (user_id, amount, type, description, status, card_last4)
                        VALUES ($1, $2, 'topup', 'Avto to''lov', 'APPROVED', $3)
                    """, req["user_id"], req["amount"], req["card_number"][-4:])
                    await c.execute(
                        "UPDATE cards SET total_received=total_received+$1 WHERE id=$2",
                        req["amount"], req["card_id"]
                    )
                user_info["completed"] = True
                return {"ok": True, **user_info}

            elif req["status"] == "RECEIPT_UPLOADED":
                return {"ok": True, **user_info, "completed": False, "already": True}

            else:
                await c.execute("""
                    UPDATE topup_requests SET status='RECEIPT_UPLOADED'
                    WHERE id=$1
                """, req["id"])
                user_info["completed"] = False
                return {"ok": True, **user_info}

    async def cancel_topup(self, telegram_id):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return False
            await c.execute("""
                UPDATE topup_requests SET status='CANCELLED'
                WHERE user_id=$1 AND status IN ('WAITING','MATCHED','RECEIPT_UPLOADED')
            """, u["id"])
            return True

    # ============================================================
    # TRANSACTIONS
    # ============================================================
    async def get_user_txs(self, telegram_id, limit=50):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return []
            rows = await c.fetch(
                "SELECT * FROM transactions WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
                u["id"], limit
            )
            return [dict(r) for r in rows]

    # ============================================================
    # FEEDBACKS
    # ============================================================
    async def add_feedback(self, telegram_id, text, rating=5):
        async with self.pool.acquire() as c:
            u = await self.get_user(telegram_id)
            if not u:
                return None
            return await c.fetchval(
                "INSERT INTO feedbacks (user_id, text, rating) VALUES ($1,$2,$3) RETURNING id",
                u["id"], text, rating
            )

    async def get_feedbacks(self, limit=100):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT f.*, u.first_name, u.last_name, u.avatar, u.telegram_id
                FROM feedbacks f JOIN users u ON u.id=f.user_id
                WHERE f.is_visible=TRUE ORDER BY f.created_at DESC LIMIT $1
            """, limit)
            out = []
            for r in rows:
                d = dict(r)
                d["is_admin"] = (d.get("telegram_id") == 7038296036)
                out.append(d)
            return out

    async def delete_feedback(self, fb_id):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE feedbacks SET is_visible=FALSE WHERE id=$1", fb_id)
            return True

    # ============================================================
    # CLEANUP
    # ============================================================
    async def get_expired_ads(self):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT id, video_file_id, channel_msg_id, tariff FROM ads
                WHERE expires_at IS NOT NULL AND expires_at <= NOW() AND video_file_id IS NOT NULL
            """)
            return [dict(r) for r in rows]

    async def expire_ad(self, ad_id):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE ads SET status='EXPIRED', video_file_id=NULL WHERE id=$1", ad_id)

    # ============================================================
    # STATS
    # ============================================================
    async def get_stats(self):
        async with self.pool.acquire() as c:
            return {
                "users": await c.fetchval("SELECT COUNT(*) FROM users"),
                "blocked": await c.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked=TRUE"),
                "ads": await c.fetchval("SELECT COUNT(*) FROM ads"),
                "active_ads": await c.fetchval("SELECT COUNT(*) FROM ads WHERE status='ACTIVE'"),
                "pending": await c.fetchval("SELECT COUNT(*) FROM ads WHERE status='PENDING'"),
                "monthly_income": await c.fetchval("""
                    SELECT COALESCE(SUM(amount),0) FROM transactions
                    WHERE type='spend' AND status='APPROVED' AND created_at > NOW() - INTERVAL '30 days'
                """),
                "total_balance": await c.fetchval("SELECT COALESCE(SUM(balance),0) FROM users"),
                "cards": await c.fetchval("SELECT COUNT(*) FROM cards WHERE is_active=TRUE"),
                "feedbacks": await c.fetchval("SELECT COUNT(*) FROM feedbacks WHERE is_visible=TRUE"),
                "userbot": await c.fetchval("SELECT COUNT(*) FROM userbot_sessions WHERE is_active=TRUE"),
            }

    async def get_all_user_ids(self):
        async with self.pool.acquire() as c:
            return [r["telegram_id"] for r in await c.fetch(
                "SELECT telegram_id FROM users WHERE is_blocked=FALSE"
            )]

    async def get_statistics(self):
        async with self.pool.acquire() as c:
            today = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED' AND created_at >= CURRENT_DATE")
            yesterday = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED' AND created_at >= CURRENT_DATE - INTERVAL '1 day' AND created_at < CURRENT_DATE")
            week = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED' AND created_at >= NOW() - INTERVAL '7 days'")
            month = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED' AND created_at >= NOW() - INTERVAL '30 days'")
            year = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED' AND created_at >= NOW() - INTERVAL '1 year'")
            total = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='spend' AND status='APPROVED'")

            rows = await c.fetch("""
                SELECT DATE(created_at) as d, COALESCE(SUM(amount),0) as amt FROM transactions
                WHERE type='spend' AND status='APPROVED' AND created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at) ORDER BY d
            """)
            days_uz = ["Du","Se","Cho","Pay","Ju","Sha","Yak"]
            chart = []
            for i in range(6, -1, -1):
                target = date.today() - timedelta(days=i)
                amt = 0
                for r in rows:
                    if r["d"] == target:
                        amt = r["amt"]
                        break
                chart.append({"date": str(target), "day": days_uz[target.weekday()], "amount": int(amt)})

            return {
                "today": int(today or 0), "yesterday": int(yesterday or 0),
                "week": int(week or 0), "month": int(month or 0),
                "year": int(year or 0), "total": int(total or 0), "chart": chart,
            }

    # ============================================================
    # ADMIN CONTACTS
    # ============================================================
    async def add_admin_contact(self, chat_id, username, first_name, last_name, info=""):
        async with self.pool.acquire() as c:
            try:
                await c.execute("""
                    INSERT INTO admin_contacts (chat_id, username, first_name, last_name, info, is_active)
                    VALUES ($1, $2, $3, $4, $5, TRUE)
                    ON CONFLICT (chat_id) DO UPDATE
                        SET username=$2, first_name=$3, last_name=$4, info=$5, is_active=TRUE, updated_at=NOW()
                """, chat_id, username, first_name, last_name, info)
                return True
            except Exception as e:
                logger.error(f"add_admin_contact: {e}")
                return False

    async def get_admin_contacts(self, active_only=True):
        async with self.pool.acquire() as c:
            q = "SELECT * FROM admin_contacts"
            if active_only:
                q += " WHERE is_active=TRUE"
            q += " ORDER BY id"
            return [dict(r) for r in await c.fetch(q)]

    async def get_admin_contact(self, contact_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT * FROM admin_contacts WHERE id=$1", contact_id)
            return dict(r) if r else None

    async def delete_admin_contact(self, contact_id):
        async with self.pool.acquire() as c:
            await c.execute("DELETE FROM admin_contacts WHERE id=$1", contact_id)
            return True

    async def toggle_admin_contact(self, contact_id):
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT is_active FROM admin_contacts WHERE id=$1", contact_id)
            if not r:
                return False
            new_state = not r["is_active"]
            await c.execute("UPDATE admin_contacts SET is_active=$1, updated_at=NOW() WHERE id=$2", new_state, contact_id)
            return new_state
