"""
Cardinal v5.6 — Sozlamalar
- Yangi bot token
- Yangi 2 kanal (private + public)
- Reklama faqat 1-kanalga chiqadi
"""
import os


# ============================================================
# DATABASE
# ============================================================
class DB:
    HOST = os.getenv("PGHOST", "localhost")
    PORT = int(os.getenv("PGPORT", 5432))
    NAME = os.getenv("PGDATABASE", "railway")
    USER = os.getenv("PGUSER", "postgres")
    PASSWORD = os.getenv("PGPASSWORD", "root")


# ============================================================
# BOT
# ============================================================
class BOT:
    # Bot
    TOKEN = os.getenv("BOT_TOKEN", "8981969442:AAELaMVuxJA9_pPAAbf6KIRFwinKrAN3GMY")
    USERNAME = "cardinal_akkaunt_bot"

    # Admin
    ADMIN_CHAT_ID = 7038296036
    ADMIN_USERNAME = "cardinal_admin"
    ADMIN_NAME = "CARDINAL ADMIN"

    # Web App URL
    WEB_APP_URL = "https://bilolmujah-hue.github.io/cardinal_github/"

    # 🔥 REKLAMA KANALI — faqat shu yerga post qilinadi (private)
    ADS_CHANNEL_ID = -1001723379807
    ADS_CHANNEL_INVITE = "https://t.me/+5XuKi8Nxoz5iODky"
    ADS_CHANNEL_NAME = "Cardinal Chat"

    # 📢 PUBLIC KANAL — faqat obuna uchun, post qilinmaydi
    PUBLIC_CHANNEL_USERNAME = "@Cardinal_PUBG"
    PUBLIC_CHANNEL_ID = -1001365422917
    PUBLIC_CHANNEL_NAME = "Cardinal PUBG"

    # Video saqlash kanali
    VIDEO_CHANNEL_ID = -1004401093865

    # Majburiy obuna kanallari (2 ta)
    REQUIRED_CHANNELS = [
        {
            "type": "invite",
            "invite": "https://t.me/+5XuKi8Nxoz5iODky",
            "id": -1001723379807,
            "name": "Cardinal Chat",
        },
        {
            "type": "username",
            "username": "@Cardinal_PUBG",
            "id": -1001365422917,
            "name": "Cardinal PUBG",
        },
    ]


# ============================================================
# USERBOT (Telethon)
# ============================================================
class USERBOT:
    API_ID = 30030023
    API_HASH = "a3a0b5d77ef12ec9ed208012844875c5"
    PHONE = os.getenv("USERBOT_PHONE", "")
    SESSION_STRING = os.getenv("USERBOT_SESSION", "")
    WATCH_BOT_USERNAME = "CardXabarBot"


# ============================================================
# JWT
# ============================================================
class JWT:
    SECRET = os.getenv(
        "JWT_SECRET",
        "cardinal-super-secret-change-in-prod-2026-xR9k"
    )
    ALGORITHM = "HS256"
    ACCESS_MINUTES = 15
    REFRESH_DAYS = 7


# ============================================================
# API
# ============================================================
class API:
    HOST = "0.0.0.0"
    PORT = int(os.getenv("PORT", 8080))
    MAX_SIZE = 200 * 1024 * 1024


# ============================================================
# TARIFLAR
# ============================================================
class T1:
    id = 1
    price = 9000
    days = 7
    type = "STANDARD"
    name = "STANDART"
    badge = None
    channel = False
    webapp = True
    top_hours = 0

class T2:
    id = 2
    price = 19000
    days = 7
    type = "STANDARD"
    name = "KANAL + WEB APP"
    badge = None
    channel = True
    webapp = True
    top_hours = 0

class T3:
    id = 3
    price = 25000
    days = 7
    type = "RARE"
    name = "RARE"
    badge = "🔥 10% SKIDKA"
    channel = True
    webapp = True
    top_hours = 0

class T4:
    id = 4
    price = 29000
    days = 7
    type = "PREMIUM"
    name = "PREMIUM VIP"
    badge = "👑 VIP"
    channel = True
    webapp = True
    top_hours = 48

TARIFFS = {1: T1, 2: T2, 3: T3, 4: T4}


# ============================================================
# VALYUTALAR
# ============================================================
CURRENCIES = {
    "UZS": {"symbol": "so'm", "flag": "🇺🇿", "name": "So'm"},
    "USD": {"symbol": "$",    "flag": "🇺🇸", "name": "Dollar"},
    "RUB": {"symbol": "₽",    "flag": "🇷🇺", "name": "Rubl"},
}


# ============================================================
# VILOYATLAR
# ============================================================
REGIONS = [
    "Toshkent", "Samarqand", "Buxoro", "Namangan", "Andijon",
    "Farg'ona", "Qashqadaryo", "Surxondaryo", "Xorazm", "Navoiy",
    "Jizzax", "Sirdaryo", "Toshkent viloyati", "Qoraqalpog'iston"
]


# ============================================================
# LIMITLAR
# ============================================================
class LIMITS:
    VIDEO_MAX_MB = 200
    VIDEO_TTL_DAYS = 7
    COLLECTION_MAX = 101
    RP_MAX_CHARS = 50
    ADD_LIST_MAX = 25
    PAYMENT_TIMEOUT_MIN = 10      # ← 10 daqiqa
    MIN_TOPUP = 1000


# ============================================================
# BOSHLANG'ICH KARTALAR
# ============================================================
INITIAL_CARDS = [
    "5614682110725894",
    "5614682513788143",
]
