"""
Cardinal v5.1 — Sozlamalar
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
    TOKEN = os.getenv("BOT_TOKEN", "8894813624:AAFCo3nDE19T8A2Ql_-W2j4-XemU4G1QcxI")
    ADMIN_CHAT_ID = 7038296036
    ADMIN_USERNAME = "cardinal_admin"
    ADMIN_NAME = "CARDINAL ADMIN"

    WEB_APP_URL = "https://ishbilol1230-dev.github.io/budilnik-app/uzbekcats.html"

    # E'lonlar kanali
    CHANNEL_USERNAME = "@tajriva2"
    CHANNEL_ID = -1004390708511

    # Video saqlash kanali
    VIDEO_CHANNEL_ID = -1004401093865

    # Majburiy obuna kanallari
    REQUIRED_CHANNELS = [
        {"username": "@tajriva2", "id": -1004390708511, "name": "Tajriva 2"},
        {"username": "@tajriva",  "id": -1004442636025, "name": "Tajriva"},
    ]


# ============================================================
# USERBOT (Telethon)
# ============================================================
class USERBOT:
    # my.telegram.org dan olingan
    API_ID = 30030023
    API_HASH = "a3a0b5d77ef12ec9ed208012844875c5"

    # Telefon raqam (ixtiyoriy)
    PHONE = os.getenv("USERBOT_PHONE", "")

    # StringSession (Railway Variables dan)
    SESSION_STRING = os.getenv("USERBOT_SESSION", "")

    # CardXabarBot username
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
    MAX_SIZE = 200 * 1024 * 1024  # 200 MB


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
    top_hours = 48  # 2 kun TOP

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
    PAYMENT_TIMEOUT_MIN = 5
    MIN_TOPUP = 1000


# ============================================================
# BOSHLANG'ICH KARTALAR
# ============================================================
INITIAL_CARDS = [
    "5614682110725894",
    "5614682513788143",
]
