"""
CARDINAL REKLAMA BOT v5.3 — Premium Design
- Chiroyli tranzaksiyalar
- Premium ko'rinishdagi xabarlar
- Zamonaviy keyboard va emoji
"""
import asyncio
import logging
import json
import base64
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    BufferedInputFile
)

from config import BOT, TARIFFS, CURRENCIES, LIMITS, REGIONS, USERBOT
from db import Database
from video_cleaner import VideoCleaner
from userbot import CardXabarWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("CardinalBot")


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================
def num(n) -> str:
    """Raqamni chiroyli formatlash: 400000 -> 400 000"""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return "0"


def fmt_price(amount, currency="UZS") -> str:
    """Narxni valyutaga qarab formatlash"""
    cur = CURRENCIES.get(currency, CURRENCIES["UZS"])
    n = int(amount or 0)
    if currency == "UZS":
        return f"{num(n)} {cur['symbol']}"
    if currency == "USD":
        return f"${n}"
    if currency == "RUB":
        return f"{num(n)} {cur['symbol']}"
    return f"{num(n)} {cur['symbol']}"


def fmt_date(date_obj, full=False) -> str:
    """Sanani formatlash"""
    if not date_obj:
        return "-"
    try:
        if isinstance(date_obj, str):
            date_obj = datetime.fromisoformat(date_obj.replace("Z", ""))
        if full:
            return date_obj.strftime("%d.%m.%Y · %H:%M")
        return date_obj.strftime("%d.%m.%Y")
    except Exception:
        return str(date_obj)


def status_emoji(status: str) -> str:
    return {
        "APPROVED": "✅",
        "PENDING": "⏳",
        "REJECTED": "❌",
    }.get(status, "⚪")


def tx_type_emoji(tx_type: str) -> tuple:
    """Qaytaradi: (emoji, label, sign)"""
    if tx_type == "topup":
        return "💰", "Hisob to'ldirish", "+"
    if tx_type == "spend":
        return "💸", "Reklama uchun", "−"
    if tx_type == "remove":
        return "⚠️", "Admin olib tashladi", "−"
    return "💳", "Boshqa", ""


def ad_status_text(status: str) -> tuple:
    """Qaytaradi: (emoji, matn)"""
    return {
        "ACTIVE": ("🟢", "Faol"),
        "PENDING": ("🟡", "Tasdiqlanmoqda"),
        "REJECTED": ("🔴", "Rad etilgan"),
        "EXPIRED": ("⚪", "Muddati o'tgan"),
    }.get(status, ("⚪", status))


# ============================================================
# CARDINAL BOT
# ============================================================
class CardinalBot:
    def __init__(self, db: Database):
        self.bot = Bot(token=BOT.TOKEN)
        self.dp = Dispatcher()
        self.db = db

        self.userbot = CardXabarWatcher(
            on_payment=self._on_payment_received,
            db=db
        )
        self.cleaner = VideoCleaner(db, self.bot)

        self._register_handlers()
        self._register_callbacks()

    # ============================================================
    # AVTOMATIK TO'LOV
    # ============================================================
    async def _on_payment_received(self, amount: int, payer_last4: str, raw: str) -> dict:
        try:
            result = await self.db.match_payment(amount, payer_last4)
            if result and result.get("ok"):
                try:
                    await self.bot.send_message(
                        result["user_tg"],
                        f"🎉 <b>TO'LOV QABUL QILINDI!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"💰 Summa: <b>{num(amount)} so'm</b>\n"
                        f"💳 Karta: <code>**** {payer_last4}</code>\n\n"
                        f"✅ Hisobingiz muvaffaqiyatli to'ldirildi\n"
                        f"🚀 Endi reklama joylashingiz mumkin!",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"User xabarnoma xato: {e}")
                return result
            return result or {"ok": False, "reason": "no_match"}
        except Exception as e:
            logger.error(f"Payment match xato: {e}", exc_info=True)
            return {"ok": False, "reason": "error"}

    # ============================================================
    # HANDLERS
    # ============================================================
    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, CommandStart())
        self.dp.message.register(self.cmd_admin, Command("admin"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.cmd_channelid, Command("channelid"))
        self.dp.message.register(self.cmd_cards, Command("cards"))
        self.dp.message.register(self.cmd_addcard, Command("addcard"))
        self.dp.message.register(self.cmd_delcard, Command("delcard"))
        self.dp.message.register(self.handle_contact, F.contact)
        self.dp.message.register(self.handle_webapp_data, F.web_app_data)
        self.dp.message.register(self.handle_profile_btn, F.text == "👤 Profilim")
        self.dp.message.register(self.handle_tx_btn, F.text == "💳 Tranzaksiya")
        self.dp.message.register(self.handle_about_btn, F.text == "ℹ️ Bot haqida")
        self.dp.message.register(self.handle_other, F.text)

    def _register_callbacks(self):
        @self.dp.callback_query(F.data == "check_sub")
        async def check_sub(cb: CallbackQuery):
            not_sub = await self._check_subscription(cb.from_user.id)
            if not_sub:
                await cb.answer("❌ Hali obuna bo'lmagansiz!", show_alert=True)
                await cb.message.edit_reply_markup(reply_markup=self._sub_kb(not_sub))
            else:
                await cb.answer("✅ Obuna tasdiqlandi!")
                try:
                    await cb.message.delete()
                except Exception:
                    pass
                u = await self.db.get_user(cb.from_user.id)
                if u and u.get("phone"):
                    await self._show_main_menu(cb.message)
                else:
                    kb = ReplyKeyboardMarkup(
                        keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
                        resize_keyboard=True, one_time_keyboard=True
                    )
                    await cb.message.answer(
                        "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                        "📱 Endi telefon raqamingizni yuboring:",
                        parse_mode="HTML", reply_markup=kb
                    )

        @self.dp.callback_query(F.data.startswith("approve_ad_"))
        async def approve_ad(cb: CallbackQuery):
            if cb.from_user.id != BOT.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True); return
            ad_id = int(cb.data.split("_")[-1])
            await self._approve_ad(ad_id, cb)

        @self.dp.callback_query(F.data.startswith("reject_ad_"))
        async def reject_ad(cb: CallbackQuery):
            if cb.from_user.id != BOT.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True); return
            ad_id = int(cb.data.split("_")[-1])
            await self._reject_ad(ad_id, cb)

    # ============================================================
    # /start
    # ============================================================
    async def cmd_start(self, message: Message):
        u = message.from_user
        if await self.db.is_blocked(u.id):
            await message.answer(
                "🚫 <b>Siz botdan bloklangansiz!</b>\n\n"
                "Savol uchun admin bilan bog'laning.",
                parse_mode="HTML"
            )
            return

        await self.db.get_or_create_user(
            telegram_id=u.id, username=u.username,
            first_name=u.first_name, last_name=u.last_name
        )

        if await self.db.is_registered(u.id):
            await self._show_main_menu(message)
            return

        not_sub = await self._check_subscription(u.id)
        if not_sub:
            await message.answer(
                "📢 <b>KANALLARGA OBUNA BO'LING</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:\n\n"
                + "\n".join(f"  {i+1}. {c['name']}" for i, c in enumerate(BOT.REQUIRED_CHANNELS))
                + "\n\n✅ Obuna bo'lgach, <b>Tekshirish</b> tugmasini bosing.",
                parse_mode="HTML",
                reply_markup=self._sub_kb(not_sub)
            )
            return

        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎮 <b>CARDINAL REKLAMA</b> — PUBG Mobile akkauntlarini sotish va sotib olish platformasi.\n\n"
            "📌 <b>Ro'yxatdan o'tish uchun</b>\n"
            "pastdagi <b>📞 Raqamni yuborish</b> tugmasini bosing.",
            parse_mode="HTML", reply_markup=kb
        )

    # ============================================================
    # MAIN MENU
    # ============================================================
    async def _show_main_menu(self, message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
            [InlineKeyboardButton(text="📢 Kanalimiz", url=f"https://t.me/{BOT.CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton(text="👨‍💻 Admin bilan bog'lanish", url=f"https://t.me/{BOT.ADMIN_USERNAME}")],
        ])
        rkb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👤 Profilim")],
                [
                    KeyboardButton(text="💳 Tranzaksiya"),
                    KeyboardButton(text="ℹ️ Bot haqida"),
                ],
            ],
            resize_keyboard=True
        )
        await message.answer(
            "🎮 <b>CARDINAL REKLAMA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 <b>Premium xizmat:</b>\n"
            "  • 🎬 Video reklama joylash\n"
            "  • 🛒 Akkaunt sotib olish\n"
            "  • 💰 Balansni avtomatik to'ldirish\n"
            "  • ⭐ Otzif qoldirish\n\n"
            "🚀 Web App orqali barcha imkoniyatlar!",
            parse_mode="HTML", reply_markup=kb
        )
        await message.answer(
            "⬇️ <b>Qo'shimcha bo'limlar:</b>",
            parse_mode="HTML", reply_markup=rkb
        )

    # ============================================================
    # COMMANDS
    # ============================================================
    async def cmd_admin(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        await message.answer(
            "🛡️ <b>ADMIN PANEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Foydalanuvchilar: <b>{num(s['users'])}</b>\n"
            f"🚫 Bloklangan: <b>{num(s['blocked'])}</b>\n"
            f"📢 Reklamalar: <b>{num(s['ads'])}</b>\n"
            f"🟢 Faol: <b>{num(s['active_ads'])}</b>\n"
            f"⏳ Kutilmoqda: <b>{num(s['pending'])}</b>\n"
            f"💳 Aktiv kartalar: <b>{num(s['cards'])}</b>\n"
            f"⭐ Otziflar: <b>{num(s['feedbacks'])}</b>\n"
            f"🤖 Userbot: <b>{'✅ Aktiv' if s.get('userbot') else '❌ Yoq'}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 Umumiy balans: <b>{num(s['total_balance'])} so'm</b>\n"
            f"📈 30 kunlik daromad: <b>{num(s['monthly_income'])} so'm</b>",
            parse_mode="HTML"
        )

    async def cmd_stats(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        await message.answer(
            f"<pre>{json.dumps(s, indent=2, ensure_ascii=False)}</pre>",
            parse_mode="HTML"
        )

    async def cmd_channelid(self, message: Message):
        await message.answer(
            f"🆔 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
            f"📁 <b>Type:</b> {message.chat.type}",
            parse_mode="HTML"
        )

    async def cmd_cards(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        cards = await self.db.get_cards(active_only=False)
        if not cards:
            await message.answer(
                "💳 <b>KARTALAR</b>\n\n"
                "❌ Karta yo'q\n\n"
                "➕ Qo'shish: <code>/addcard 5614682110725894</code>",
                parse_mode="HTML"
            )
            return
        lines = ["💳 <b>KARTALAR</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
        for i, c in enumerate(cards, 1):
            st = "🟢" if c["is_active"] else "🔴"
            lines.append(
                f"{st} <b>#{i}</b> · <code>{c['number']}</code>\n"
                f"     💰 {num(c['total_received'])} so'm yig'ildi\n"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_addcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "💳 <b>Karta qo'shish</b>\n\n"
                "Format: <code>/addcard 5614682110725894</code>",
                parse_mode="HTML"
            )
            return
        num_str = parts[1].strip().replace(" ", "")
        if not num_str.isdigit() or len(num_str) != 16:
            await message.answer("❌ 16 xonali raqam kiriting")
            return
        ok = await self.db.add_card(num_str)
        await message.answer("✅ <b>Qo'shildi</b>" if ok else "❌ Allaqachon mavjud", parse_mode="HTML")

    async def cmd_delcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Format: <code>/delcard 1</code>", parse_mode="HTML")
            return
        try:
            cid = int(parts[1])
            await self.db.remove_card(cid)
            await message.answer(f"✅ <b>Karta #{cid} o'chirildi</b>", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Xato: {e}")

    # ============================================================
    # CONTACT
    # ============================================================
    async def handle_contact(self, message: Message):
        c = message.contact
        phone = c.phone_number.replace("+", "").replace(" ", "")
        if phone.startswith("998"):
            phone = phone[3:]

        u = message.from_user
        not_sub = await self._check_subscription(u.id)
        if not_sub:
            await message.answer(
                "📢 <b>Avval kanallarga obuna bo'ling!</b>",
                parse_mode="HTML",
                reply_markup=self._sub_kb(not_sub)
            )
            return

        await self.db.get_or_create_user(
            telegram_id=u.id, username=u.username,
            first_name=u.first_name, last_name=u.last_name
        )
        await self.db.update_phone(u.id, phone)
        await message.answer(
            "✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎉 Endi siz platformadan to'liq foydalanishingiz mumkin!",
            parse_mode="HTML"
        )
        await self._show_main_menu(message)

    # ============================================================
    # PROFILE (premium)
    # ============================================================
    async def handle_profile_btn(self, message: Message):
        u = await self.db.get_user(message.from_user.id)
        if not u:
            await message.answer("❌ /start bosing"); return

        admin_label = " 🛡️ <b>ADMIN</b>" if u.get("is_admin") else ""
        status_emoji_ = "🟢" if not u.get("is_blocked") else "🔴"
        status_text = "Faol" if not u.get("is_blocked") else "Bloklangan"

        # Reklamalar soni
        async with self.db.pool.acquire() as c:
            total_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1", u["id"])
            active_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='ACTIVE'", u["id"])
            pending_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='PENDING'", u["id"])

        text = (
            f"╔══════════════════════════╗\n"
            f"   👤 <b>PROFILINGIZ</b>{admin_label}\n"
            f"╚══════════════════════════╝\n\n"
            f"🆔 <b>ID:</b> <code>{u['telegram_id']}</code>\n"
            f"📛 <b>Ism:</b> {u.get('first_name') or '-'}\n"
            f"📛 <b>Familiya:</b> {u.get('last_name') or '-'}\n"
            f"🔗 <b>Username:</b> @{u.get('username') or '-'}\n"
            f"📱 <b>Telefon:</b> +998{u.get('phone') or '-'}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Sarflangan:</b> {num(u['spent'])} so'm\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 <b>Reklamalar:</b>\n"
            f"  • 📊 Jami: <b>{total_ads}</b>\n"
            f"  • 🟢 Faol: <b>{active_ads}</b>\n"
            f"  • 🟡 Kutilmoqda: <b>{pending_ads}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Ro'yxatdan: <b>{fmt_date(u.get('created_at'))}</b>\n"
            f"📊 Holat: {status_emoji_} <b>{status_text}</b>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    # ============================================================
    # TRANZAKSIYALAR (premium dizayn)
    # ============================================================
    async def handle_tx_btn(self, message: Message):
        user_id = message.from_user.id
        if await self.db.is_blocked(user_id):
            await message.answer("🚫 Siz bloklangansiz!")
            return

        u = await self.db.get_user(user_id)
        txs = await self.db.get_user_txs(user_id, limit=20)

        if not txs:
            await message.answer(
                "╔══════════════════════════╗\n"
                "  💳 <b>TRANZAKSIYALAR</b>\n"
                "╚══════════════════════════╝\n\n"
                "😔 Hozircha tranzaksiyalar yo'q\n\n"
                f"💰 Joriy balans: <b>{num(u['balance'])} so'm</b>\n\n"
                "💡 Hisobni to'ldirish uchun:\n"
                "🌐 Web App → Hisobni to'ldirish",
                parse_mode="HTML"
            )
            return

        # Header
        header = (
            f"╔══════════════════════════╗\n"
            f"  💳 <b>TRANZAKSIYALAR TARIXI</b>\n"
            f"╚══════════════════════════╝\n\n"
            f"💰 <b>Joriy balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Jami sarflangan:</b> {num(u['spent'])} so'm\n"
            f"📊 <b>Oxirgi {len(txs)} ta tranzaksiya</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Har bir tranzaksiya
        lines = [header]
        for tx in txs:
            emoji, label, sign = tx_type_emoji(tx["type"])
            st_emoji = status_emoji(tx["status"])
            amount = tx["amount"]
            date_str = fmt_date(tx["created_at"], full=True)
            desc = (tx.get("description") or "")[:40]

            # Summa rangi
            if sign == "+":
                amount_str = f"<b>{sign}{num(amount)} so'm</b>"
            elif sign == "−":
                amount_str = f"<b>{sign}{num(amount)} so'm</b>"
            else:
                amount_str = f"<b>{num(amount)} so'm</b>"

            lines.append(
                f"{st_emoji} {emoji} <b>{label}</b>\n"
                f"   {amount_str}\n"
                f"   🕐 {date_str}\n"
                f"   📝 <i>{desc}</i>\n"
                f"   ─────────────────\n"
            )

        # Footer
        lines.append(
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Har bir to'lov avtomatik tasdiqlanadi</i>"
        )

        text = "\n".join(lines)

        # Telegram limit 4096 — bo'lib yuboramiz
        if len(text) > 4000:
            chunks = []
            current = ""
            for line in lines:
                if len(current) + len(line) > 3800:
                    chunks.append(current)
                    current = line
                else:
                    current += line
            if current:
                chunks.append(current)

            for chunk in chunks:
                await message.answer(chunk, parse_mode="HTML")
                await asyncio.sleep(0.3)
        else:
            await message.answer(text, parse_mode="HTML")

    # ============================================================
    # BOT HAQIDA (premium)
    # ============================================================
    async def handle_about_btn(self, message: Message):
        text = (
            "╔══════════════════════════╗\n"
            "  ℹ️ <b>BOT HAQIDA</b>\n"
            "╚══════════════════════════╝\n\n"
            "🎮 <b>CARDINAL REKLAMA</b>\n"
            "PUBG Mobile akkauntlarini sotish va sotib olish uchun premium platforma.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✨ <b>IMKONIYATLAR:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📹 Video reklama (10 daqiqagacha)\n"
            "🛒 Akkaunt sotib olish\n"
            "❤️ Saqlangan akkauntlar\n"
            "⭐ Otzif qoldirish\n"
            "💰 Avtomatik balans to'ldirish\n"
            "🛡️ Xavfsiz va ishonchli\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💎 <b>TARIFLAR:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"1️⃣ STANDART\n"
            f"    💰 {num(TARIFFS[1].price)} so'm · 7 kun\n"
            f"    📍 Faqat Web App'da\n\n"
            f"2️⃣ KANAL + WEB APP\n"
            f"    💰 {num(TARIFFS[2].price)} so'm · 7 kun\n"
            f"    📍 Kanal + Web App\n\n"
            f"3️⃣ RARE 🔥\n"
            f"    💰 {num(TARIFFS[3].price)} so'm · 7 kun\n"
            f"    📍 Kanal + Web App\n"
            f"    🎁 10% skidka keyingi reklamaga\n\n"
            f"4️⃣ PREMIUM VIP 👑\n"
            f"    💰 {num(TARIFFS[4].price)} so'm · 7 kun\n"
            f"    📍 Kanal + Web App\n"
            f"    ⚡ 48 soat TOP'da\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💳 <b>TO'LOV:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🤖 Web App orqali avtomatik\n"
            "⚡ 5 daqiqada hisobingizga tushadi\n\n"
            f"📞 <b>Qo'llab-quvvatlash:</b>\n"
            f"👨‍💻 @{BOT.ADMIN_USERNAME}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
            [InlineKeyboardButton(text="👨‍💻 Admin bilan bog'lanish", url=f"https://t.me/{BOT.ADMIN_USERNAME}")],
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    async def handle_webapp_data(self, message: Message):
        try:
            data = json.loads(message.web_app_data.data)
            logger.info(f"WebApp: {data}")
        except Exception:
            pass

    async def handle_other(self, message: Message):
        if message.from_user.id == BOT.ADMIN_CHAT_ID:
            await message.answer(
                "🛡️ <b>ADMIN BUYRUQLAR</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "/admin — statistika\n"
                "/stats — batafsil (JSON)\n"
                "/cards — kartalar\n"
                "/addcard — karta qo'shish\n"
                "/delcard — karta o'chirish\n"
                "/channelid — kanal ID",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "🎮 <b>Xush kelibsiz!</b>\n\n"
                "Boshlash uchun /start bosing",
                parse_mode="HTML"
            )

    # ============================================================
    # SUBSCRIPTION
    # ============================================================
    async def _check_subscription(self, user_id: int) -> list:
        not_sub = []
        for ch in BOT.REQUIRED_CHANNELS:
            try:
                m = await self.bot.get_chat_member(ch["username"], user_id)
                if m.status in ("left", "kicked", "banned"):
                    not_sub.append(ch["username"])
            except Exception:
                not_sub.append(ch["username"])
        return not_sub

    def _sub_kb(self, not_sub):
        btns = []
        for ch in BOT.REQUIRED_CHANNELS:
            if ch["username"] in not_sub:
                btns.append([InlineKeyboardButton(
                    text=f"📢 {ch['name']}",
                    url=f"https://t.me/{ch['username'].replace('@','')}"
                )])
        btns.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
        return InlineKeyboardMarkup(inline_keyboard=btns)

    # ============================================================
    # ADMIN APPROVE/REJECT
    # ============================================================
    async def _approve_ad(self, ad_id: int, cb: CallbackQuery):
        ad = await self.db.get_ad(ad_id)
        if not ad:
            await cb.answer("❌ Topilmadi"); return

        top_until = None
        t = TARIFFS.get(ad["tariff"], TARIFFS[1])
        if getattr(t, "top_hours", 0) > 0:
            top_until = datetime.now() + timedelta(hours=t.top_hours)

        async with self.db.pool.acquire() as c:
            await c.execute("UPDATE ads SET top_until=$1 WHERE id=$2", top_until, ad_id)

        await self.db.update_ad_status(ad_id, "ACTIVE")

        if t.channel and ad.get("video_file_id"):
            await self._post_to_channel(ad)

        try:
            await self.bot.send_message(
                ad["seller_tg"],
                "✅ <b>REKLAMANGIZ TASDIQLANDI!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📢 <b>{ad['title']}</b>\n"
                f"🆔 #{ad_id}\n\n"
                "🎉 Endi e'loningiz Web App'da ko'rinadi!",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("✅ Tasdiqlandi")
        await cb.message.answer(f"✅ <b>E'lon #{ad_id} tasdiqlandi</b>", parse_mode="HTML")

    async def _reject_ad(self, ad_id: int, cb: CallbackQuery):
        ad = await self.db.get_ad(ad_id)
        if not ad:
            await cb.answer("❌ Topilmadi"); return
        await self.db.update_ad_status(ad_id, "REJECTED", "Admin rad etdi")
        t = TARIFFS.get(ad["tariff"], TARIFFS[1])
        await self.db.update_balance(ad["seller_tg"], t.price, "topup", "Rad etilgan reklama qaytarildi")
        try:
            await self.bot.send_message(
                ad["seller_tg"],
                "❌ <b>REKLAMA RAD ETILDI</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📢 <b>{ad['title']}</b>\n"
                f"💰 Pul qaytarildi: <b>{num(t.price)} so'm</b>\n\n"
                "📞 Sabab uchun admin bilan bog'laning",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ Rad etildi")

    # ============================================================
    # KANALGA JOYLASH
    # ============================================================
    async def _post_to_channel(self, ad: dict):
        try:
            acc = ad.get("account_data", {}) or {}
            cur = CURRENCIES.get(ad.get("currency", "UZS"), CURRENCIES["UZS"])

            lines = [
                "🎮 <b>PUBG MOBILE AKKOUNT</b>",
                "━━━━━━━━━━━━━━━━━━━━",
                "",
                f"📈 <b>LVL:</b> {acc.get('level', '-')}",
                f"🎯 <b>Kolleksiya:</b> {acc.get('collection', '-')}",
                f"🏆 <b>RP:</b> {acc.get('rp', '-')}",
                f"👕 <b>Mifik kiyimlar:</b> {acc.get('mythic_clothes', 0)} ta",
                "",
                "💎 <b>Redkiy skinlar:</b>",
            ]
            for s in (acc.get("rare_skins") or [])[:25]:
                lines.append(f"  • {s}")
            if not acc.get("rare_skins"):
                lines.append("  • -")

            if acc.get("x_costume"):
                lines.append("")
                lines.append("🎁 <b>X-KOSTYUM:</b>")
                for s in acc["x_costume"][:25]:
                    lines.append(f"  • {s}")

            lines.append("")
            lines.append(f"🔫 <b>Kuchaytirilgan qurollar ({acc.get('guns_count', 0)}):</b>")
            for g in (acc.get("guns") or [])[:25]:
                lines.append(f"  • {g}")
            if not acc.get("guns"):
                lines.append("  • -")

            if acc.get("supar_car"):
                lines.append("")
                lines.append("🚗 <b>SUPAR-CAR:</b>")
                for s in acc["supar_car"][:25]:
                    lines.append(f"  • {s}")

            linked = acc.get("linked") or []
            lines.append("")
            lines.append(f"🔗 <b>Ulangan:</b> {', '.join(linked) if linked else '-'}")
            lines.append(f"🏠 <b>Manzil:</b> {ad.get('location', '-')}")
            if ad.get("full_location"):
                lines.append(f"📍 {ad['full_location']}")

            lines.append("")
            lines.append(f"💰 <b>NARXI: {num(ad['price'])} {cur['symbol']}</b> {cur['flag']}")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🆔 E'lon: #{ad['id']}")

            text = "\n".join(lines)

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="📢 Reklama bermoqchiman",
                    url=f"{BOT.WEB_APP_URL}?open=create"
                )
            ]])

            if ad.get("video_file_id"):
                msg = await self.bot.send_video(
                    BOT.CHANNEL_ID,
                    ad["video_file_id"],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb
                )
            else:
                msg = await self.bot.send_message(
                    BOT.CHANNEL_ID, text,
                    parse_mode="HTML", reply_markup=kb
                )
            await self.db.update_ad_status(ad["id"], "ACTIVE", channel_msg_id=msg.message_id)
            logger.info(f"📢 #{ad['id']} kanalga joylandi")
        except Exception as e:
            logger.error(f"Kanalga joylash xato: {e}", exc_info=True)

    # ============================================================
    # ADMIN NOTIFY
    # ============================================================
    async def notify_admin_new_ad(self, ad: dict):
        try:
            cur = CURRENCIES.get(ad.get("currency", "UZS"), CURRENCIES["UZS"])
            text = (
                "🆕 <b>YANGI REKLAMA</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝 <b>{ad['title']}</b>\n"
                f"💰 {num(ad['price'])} {cur['symbol']} {cur['flag']}\n"
                f"📍 {ad.get('location', '-')}\n"
                f"🎯 Tarif: {ad.get('tariff')}\n"
                f"🆔 <code>{ad['id']}</code>\n\n"
                "👇 Tasdiqlaysizmi?"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_ad_{ad['id']}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_ad_{ad['id']}"),
            ]])
            if ad.get("video_file_id"):
                await self.bot.send_video(
                    BOT.ADMIN_CHAT_ID, ad["video_file_id"],
                    caption=text, parse_mode="HTML", reply_markup=kb
                )
            else:
                await self.bot.send_message(
                    BOT.ADMIN_CHAT_ID, text,
                    parse_mode="HTML", reply_markup=kb
                )
        except Exception as e:
            logger.error(f"Admin notify xato: {e}")

    # ============================================================
    # START
    # ============================================================
    async def start(self):
        logger.info("🚀 CardinalBot v5.3 ishga tushdi")
        await self.userbot.start()
        await self.cleaner.start()
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.cleaner.stop()
        await self.userbot.stop()
        await self.bot.session.close()
