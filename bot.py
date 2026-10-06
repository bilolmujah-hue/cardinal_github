"""
Cardinal Bot v6.2 - Premium Emoji + Button Icons + Clickable Footer
- Barcha xabarlar premium emoji bilan
- Inline tugmalarda premium emoji ikonkalar
- Kanal posti ham premium
- Sonlar qalin shriftda
- Footer havolalar bosiladigan
"""
import asyncio
import logging
import json
import base64
import re
from html import escape as html_escape
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
# KANAL FOOTER — bosiladigan havolalar
# ============================================================
CHANNEL_FOOTER_HTML = (
    '📌 <a href="https://t.me/cardinal_savdo">Kanalimiz</a>\n'
    '🤝 <a href="https://t.me/Cardinal_G">Garant uchun</a>\n'
    '💰 <a href="https://t.me/cardinal_uc">UC Servis</a>\n'
    '✔️ <a href="https://t.me/Cardinal_pubg">Asosiy kanal</a>'
)


# ============================================================
# PREMIUM EMOJI
# ============================================================
PREMIUM_EMOJI = {
    "✔️": "5206607081334906820",
    "❌": "5210952531676504517",
    "⌛️": "5296482716567495148",
    "⚠️": "5447644880824181073",
    "🚫": "5240241223632954241",
    "🟢": "5832572966721818453",
    "🔴": "5411225014148014586",
    "▶️": "5348125953090403204",
    "⏳": "5368380585066665290",
    "⛔️": "5370675038200541160",
    "👤": "5879770735999717115",
    "👥": "5372926953978341366",
    "🆔": "5014902839575577394",
    "🧾": "5444856076954520455",
    "🖥": "5282843764451195532",
    "📱": "5355116622250026900",
    "📞": "5467539229468793355",
    "📲": "5406809207947142040",
    "🔗": "5271604874419647061",
    "❤️": "5354817009626425681",
    "👑": "5217822164362739968",
    "👋": "5413694143601842851",
    "🎮": "5361741454685256344",
    "📌": "5397782960512444700",
    "🌐": "5447410659077661506",
    "📢": "5278256077954105203",
    "💳": "5445353829304387411",
    "ℹ️": "5334544901428229844",
    "🛡": "5251203410396458957",
    "🤖": "5287684458881756303",
    "🗓": "5413879192267805083",
    "📁": "5336899419679792193",
    "📊": "5231200819986047254",
    "📈": "5244837092042750681",
    "💰": "5224257782013769471",
    "💸": "5231449120635370684",
    "💵": "5409048419211682843",
    "➕": "5397916757333654639",
    "🔜": "5440621591387980068",
    "🎬": "5375464961822695044",
    "🛒": "5312361253610475399",
    "🏆": "5226431245918942763",
    "🎯": "5256131095094652290",
    "👕": "5204355388895410111",
    "🎁": "5203996991054432397",
    "🚗": "5233638613358486264",
    "🔫": "5192724084881892602",
    "💎": "5427168083074628963",
    "📍": "5391032818111363540",
    "🏠": "5416041192905265756",
    "⚡️": "5456140674028019486",
    "🎉": "5461151367559141950",
    "🚀": "5188481279963715781",
    "⭐️": "5438496463044752972",
    "💡": "5422439311196834318",
    "🆕": "5382357040008021292",
    "✉️": "5253742260054409879",
    "⬇️": "5406745015365943482",
    "💬": "5253742260054409879",
}

# Qisqa nomlar — tugma ikonkalari uchun
EMOJI_ID = {
    "webapp": "5447410659077661506",
    "channel": "5278256077954105203",
    "check": "5206607081334906820",
    "cross": "5210952531676504517",
    "person": "5879770735999717115",
    "phone": "5467539229468793355",
    "card": "5445353829304387411",
    "info": "5334544901428229844",
    "shield": "5251203410396458957",
    "money": "5224257782013769471",
    "game": "5361741454685256344",
    "message": "5253742260054409879",
    "wallet": "5445353829304387411",
}

_EMOJI_KEYS = sorted(PREMIUM_EMOJI.keys(), key=len, reverse=True)
_EMOJI_PATTERN = re.compile("|".join(re.escape(e) for e in _EMOJI_KEYS))


def pe(text: str) -> str:
    if not text:
        return text
    def repl(m):
        emoji = m.group(0)
        eid = PREMIUM_EMOJI.get(emoji)
        if eid:
            return f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>'
        return emoji
    return _EMOJI_PATTERN.sub(repl, text)


# ============================================================
# HELPERS
# ============================================================
def num(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return "0"


def bold_numbers(text: str) -> str:
    """Matndagi mustaqil sonlarni <b> ga o'raydi (harflar ichidagi sonlar tegilmaydi)."""
    if not text:
        return text
    return re.sub(
        r'(?<![A-Za-z])(\d+)(?![A-Za-z])',
        lambda m: f'<b>{m.group(1)}</b>',
        str(text)
    )


def fmt_price(amount, currency="UZS") -> str:
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
    if not date_obj:
        return "-"
    try:
        if isinstance(date_obj, str):
            date_obj = datetime.fromisoformat(date_obj.replace("Z", ""))
        return date_obj.strftime("%d.%m.%Y · %H:%M") if full else date_obj.strftime("%d.%m.%Y")
    except Exception:
        return str(date_obj)


def status_emoji(status: str) -> str:
    return {
        "APPROVED": "✔️",
        "PENDING": "⏳",
        "REJECTED": "❌",
        "ACTIVE": "🟢",
    }.get(status, "⚪")


def tx_type_emoji(tx_type: str):
    if tx_type == "topup":
        return "💰", "Hisob to'ldirish", "+"
    if tx_type == "spend":
        return "💸", "Reklama uchun", "-"
    if tx_type == "remove":
        return "⚠️", "Admin olib tashladi", "-"
    return "💳", "Boshqa", ""


def safe_name(u) -> str:
    if not u:
        return "do'stim"
    name = (getattr(u, "first_name", None) or getattr(u, "username", None) or "do'stim").strip()
    if not name:
        return "do'stim"
    return html_escape(name)


def _json_default(obj):
    try:
        return str(obj)
    except Exception:
        return None


def ikb(text: str, emoji_key: str = None, **kwargs) -> InlineKeyboardButton:
    """Premium emoji ikonka bilan InlineKeyboardButton yasash."""
    if emoji_key and emoji_key in EMOJI_ID:
        try:
            return InlineKeyboardButton(
                text=text,
                icon_custom_emoji_id=EMOJI_ID[emoji_key],
                **kwargs
            )
        except TypeError:
            pass
    return InlineKeyboardButton(text=text, **kwargs)


# ============================================================
# BOT
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

    async def _on_payment_received(self, amount: int, payer_last4: str, raw: str) -> dict:
        try:
            result = await self.db.match_payment(amount, payer_last4)
            if result and result.get("ok"):
                logger.info(f"To'lov aniqlandi: {amount} so'm (***{payer_last4}) - silent")
                return result
            return result or {"ok": False, "reason": "no_match"}
        except Exception as e:
            logger.error(f"Payment match xato: {e}", exc_info=True)
            return {"ok": False, "reason": "error"}

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
                await cb.answer("✔️ Obuna tasdiqlandi!")
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
                        pe("✔️ <b>Obuna tasdiqlandi!</b>\n\n"
                           "📱 Endi telefon raqamingizni yuboring:"),
                        parse_mode="HTML", reply_markup=kb
                    )

        @self.dp.callback_query(F.data.startswith("approve_ad_"))
        async def approve_ad(cb: CallbackQuery):
            if cb.from_user.id != BOT.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return
            ad_id = int(cb.data.split("_")[-1])
            await self._approve_ad(ad_id, cb)

        @self.dp.callback_query(F.data.startswith("reject_ad_"))
        async def reject_ad(cb: CallbackQuery):
            if cb.from_user.id != BOT.ADMIN_CHAT_ID:
                await cb.answer("❌ Ruxsat yo'q", show_alert=True)
                return
            ad_id = int(cb.data.split("_")[-1])
            await self._reject_ad(ad_id, cb)

    # ============================================================
    # COMMANDS
    # ============================================================
    async def cmd_start(self, message: Message):
        u = message.from_user
        if await self.db.is_blocked(u.id):
            await message.answer(
                pe("🚫 <b>Siz botdan bloklangansiz!</b>\n\n"
                   "Savol uchun admin bilan bog'laning."),
                parse_mode="HTML"
            )
            return

        await self.db.get_or_create_user(
            telegram_id=u.id, username=u.username,
            first_name=u.first_name, last_name=u.last_name
        )

        args = (message.text or "").split(maxsplit=1)
        if len(args) > 1 and args[1].strip() == "create":
            if await self.db.is_registered(u.id):
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    ikb("Reklama berish", "channel",
                        web_app=WebAppInfo(url=BOT.WEB_APP_URL + "?open=create"))
                ]])
                await message.answer(
                    pe("📢 <b>REKLAMA BERISH</b>\n\n"
                       "Quyidagi tugmani bosing va tarifni tanlang:"),
                    parse_mode="HTML", reply_markup=kb
                )
                return

        if await self.db.is_registered(u.id):
            await self._show_main_menu(message)
            return

        not_sub = await self._check_subscription(u.id)
        if not_sub:
            await message.answer(
                pe("📢 <b>KANALLARGA OBUNA BO'LING</b>\n\n"
                   "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:\n\n"
                   + "\n".join(f"  {i+1}. {c['name']}" for i, c in enumerate(BOT.REQUIRED_CHANNELS))
                   + "\n\n✔️ Obuna bo'lgach, <b>Tekshirish</b> tugmasini bosing."),
                parse_mode="HTML",
                reply_markup=self._sub_kb(not_sub)
            )
            return

        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        name = safe_name(u)
        await message.answer(
            pe(f"👋 <b>ASSALOMU ALAYKUM, {name}!</b>\n\n"
               "🎮 <b>CARDINAL AKKAUNT</b>\n"
               "PUBG Mobile akkauntlarini ishonchli sotish va sotib olish platformasi!\n\n"
               "📌 <b>Ro'yxatdan o'tish uchun</b>\n"
               "pastdagi <b>📞 Raqamni yuborish</b> tugmasini bosing."),
            parse_mode="HTML", reply_markup=kb
        )

    async def _show_main_menu(self, message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [ikb("Web App ni ochish", "webapp",
                 web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
            [ikb("Asosiy kanal", "channel", url=BOT.ADS_CHANNEL_INVITE)],
            [ikb(BOT.PUBLIC_CHANNEL_NAME, "channel",
                 url=f"https://t.me/{BOT.PUBLIC_CHANNEL_USERNAME.replace('@','')}")],
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
            pe("🎮 <b>CARDINAL AKKAUNT</b>\n\n"
               "💎 <b>Premium xizmat:</b>\n"
               "  • 🎬 Video reklama joylash\n"
               "  • 🛒 Akkaunt sotish va sotib olish\n"
               "  • 💰 Balansni avtomatik to'ldirish\n"
               "  • ⭐️ Otzif qoldirish\n\n"
               "🚀 Web App orqali barcha imkoniyatlar!"),
            parse_mode="HTML", reply_markup=kb
        )
        await message.answer(
            pe("⬇️ <b>Qo'shimcha bo'limlar:</b>"),
            parse_mode="HTML", reply_markup=rkb
        )

    async def cmd_admin(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        days = await self.db.get_ad_days()
        await message.answer(
            pe("🛡 <b>ADMIN PANEL</b>\n\n"
               f"👥 Foydalanuvchilar: <b>{num(s['users'])}</b>\n"
               f"🚫 Bloklangan: <b>{num(s['blocked'])}</b>\n"
               f"📢 Reklamalar: <b>{num(s['ads'])}</b>\n"
               f"🟢 Faol: <b>{num(s['active_ads'])}</b>\n"
               f"⏳ Kutilmoqda: <b>{num(s['pending'])}</b>\n"
               f"💳 Aktiv kartalar: <b>{num(s['cards'])}</b>\n"
               f"⭐️ Otziflar: <b>{num(s['feedbacks'])}</b>\n"
               f"🤖 Userbot: <b>{'✔️ Aktiv' if s.get('userbot') else '❌ Yoq'}</b>\n"
               f"🗓 Reklama muddati: <b>{days} kun</b>\n\n"
               f"💵 Umumiy balans: <b>{num(s['total_balance'])} so'm</b>\n"
               f"📈 30 kunlik daromad: <b>{num(s['monthly_income'])} so'm</b>"),
            parse_mode="HTML"
        )

    async def cmd_stats(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        text = json.dumps(s, indent=2, ensure_ascii=False, default=_json_default)
        await message.answer(f"<pre>{text}</pre>", parse_mode="HTML")

    async def cmd_channelid(self, message: Message):
        await message.answer(
            pe(f"🆔 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
               f"📁 <b>Type:</b> {message.chat.type}"),
            parse_mode="HTML"
        )

    async def cmd_cards(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        cards = await self.db.get_cards(active_only=False)
        if not cards:
            await message.answer(
                pe("💳 <b>KARTALAR</b>\n\n"
                   "❌ Karta yo'q\n\n"
                   "➕ Qo'shish: <code>/addcard 5614682110725894 Ism Familiya</code>"),
                parse_mode="HTML"
            )
            return
        lines = ["💳 <b>KARTALAR</b>\n\n"]
        for i, c in enumerate(cards, 1):
            st = "🟢" if c["is_active"] else "🔴"
            holder = c.get("holder") or "-"
            lines.append(
                f"{st} <b>#{i}</b> · <code>{c['number']}</code>\n"
                f"     👤 {holder}\n"
                f"     💰 {num(c['total_received'])} so'm yig'ildi\n"
            )
        await message.answer(pe("\n".join(lines)), parse_mode="HTML")

    async def cmd_addcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                pe("💳 <b>Karta qo'shish</b>\n\n"
                   "Format: <code>/addcard 5614682110725894 Ism Familiya</code>"),
                parse_mode="HTML"
            )
            return
        num_str = parts[1].strip().replace(" ", "")
        holder = parts[2].strip()
        if not num_str.isdigit() or len(num_str) != 16:
            await message.answer("❌ 16 xonali raqam kiriting")
            return
        if not holder:
            await message.answer("❌ Karta egasining ism-familiyasini kiriting")
            return
        ok = await self.db.add_card(num_str, holder.upper())
        await message.answer(
            pe("✔️ <b>Qo'shildi</b>" if ok else "❌ Xatolik"),
            parse_mode="HTML"
        )

    async def cmd_delcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(pe("Format: <code>/delcard 1</code>"), parse_mode="HTML")
            return
        try:
            cid = int(parts[1])
            await self.db.remove_card(cid)
            await message.answer(pe(f"✔️ <b>Karta #{cid} o'chirildi</b>"), parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Xato: {e}")

    async def handle_contact(self, message: Message):
        c = message.contact
        phone = c.phone_number.replace("+", "").replace(" ", "")
        if phone.startswith("998"):
            phone = phone[3:]

        u = message.from_user
        not_sub = await self._check_subscription(u.id)
        if not_sub:
            await message.answer(
                pe("📢 <b>Avval kanallarga obuna bo'ling!</b>"),
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
            pe("✔️ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n\n"
               "🎉 Endi siz platformadan to'liq foydalanishingiz mumkin!"),
            parse_mode="HTML"
        )
        await self._show_main_menu(message)

    async def handle_profile_btn(self, message: Message):
        u = await self.db.get_user(message.from_user.id)
        if not u:
            await message.answer("❌ /start bosing")
            return

        admin_label = " 🛡 <b>ADMIN</b>" if u.get("is_admin") else ""
        st_emoji = "🟢" if not u.get("is_blocked") else "🔴"
        status_text = "Faol" if not u.get("is_blocked") else "Bloklangan"

        async with self.db.pool.acquire() as c:
            total_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1", u["id"])
            active_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='ACTIVE'", u["id"])
            pending_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='PENDING'", u["id"])

        text = (
            f"👤 <b>PROFILINGIZ</b>{admin_label}\n\n"
            f"🆔 <b>ID:</b> <code>{u['telegram_id']}</code>\n"
            f"🧾 <b>Ism:</b> {u.get('first_name') or '-'}\n"
            f"🧾 <b>Familiya:</b> {u.get('last_name') or '-'}\n"
            f"🔗 <b>Username:</b> @{u.get('username') or '-'}\n"
            f"📱 <b>Telefon:</b> +998{u.get('phone') or '-'}\n\n"
            f"💰 <b>Balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Sarflangan:</b> {num(u['spent'])} so'm\n\n"
            "📢 <b>Reklamalar:</b>\n"
            f"  • 📊 Jami: <b>{total_ads}</b>\n"
            f"  • 🟢 Faol: <b>{active_ads}</b>\n"
            f"  • ▶️ Kutilmoqda: <b>{pending_ads}</b>\n\n"
            f"🗓 Ro'yxatdan: <b>{fmt_date(u.get('created_at'))}</b>\n"
            f"📊 Holat: {st_emoji} <b>{status_text}</b>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [ikb("Web App ni ochish", "webapp",
                 web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
        ])
        await message.answer(pe(text), parse_mode="HTML", reply_markup=kb)

    async def handle_tx_btn(self, message: Message):
        user_id = message.from_user.id
        if await self.db.is_blocked(user_id):
            await message.answer(pe("🚫 Siz bloklangansiz!"), parse_mode="HTML")
            return

        u = await self.db.get_user(user_id)
        txs = await self.db.get_user_txs(user_id, limit=20)

        if not txs:
            await message.answer(
                pe("💳 <b>TRANZAKSIYALAR</b>\n\n"
                   "😔 Hozircha tranzaksiyalar yo'q\n\n"
                   f"💰 Joriy balans: <b>{num(u['balance'])} so'm</b>\n\n"
                   "💡 Hisobni to'ldirish uchun:\n"
                   "🌐 Web App → Hisobni to'ldirish"),
                parse_mode="HTML"
            )
            return

        header = (
            "💳 <b>TRANZAKSIYALAR TARIXI</b>\n\n"
            f"💰 <b>Joriy balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Jami sarflangan:</b> {num(u['spent'])} so'm\n"
            f"📊 <b>Oxirgi {len(txs)} ta tranzaksiya</b>\n\n"
        )

        lines = [header]
        for tx in txs:
            emoji, label, sign = tx_type_emoji(tx["type"])
            st_emoji = status_emoji(tx["status"])
            amount = tx["amount"]
            date_str = fmt_date(tx["created_at"], full=True)
            desc = (tx.get("description") or "")[:40]

            if sign in ("+", "-"):
                amount_str = f"<b>{sign}{num(amount)} so'm</b>"
            else:
                amount_str = f"<b>{num(amount)} so'm</b>"

            lines.append(
                f"{st_emoji} {emoji} <b>{label}</b>\n"
                f"   {amount_str}\n"
                f"   🔜 {date_str}\n"
                f"   🖥 <i>{desc}</i>\n"
                f"   -----------------\n"
            )

        lines.append("💡 <i>Har bir to'lov avtomatik tasdiqlanadi</i>")

        text = "\n".join(lines)

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
                await message.answer(pe(chunk), parse_mode="HTML")
                await asyncio.sleep(0.3)
        else:
            await message.answer(pe(text), parse_mode="HTML")

    async def handle_about_btn(self, message: Message):
        days = await self.db.get_ad_days()
        text = (
            "ℹ️ <b>BOT HAQIDA</b>\n\n"
            "🎮 <b>CARDINAL AKKAUNT</b>\n"
            "PUBG Mobile akkauntlarini sotish va sotib olish uchun premium platforma.\n\n"
            "✨ <b>IMKONIYATLAR:</b>\n\n"
            "🎬 Video reklama (10 daqiqagacha)\n"
            "🛒 Akkaunt sotib olish\n"
            "❤️ Saqlangan akkauntlar\n"
            "⭐️ Otzif qoldirish\n"
            "💰 Avtomatik balans to'ldirish\n"
            "🛡 Xavfsiz va ishonchli\n\n"
            "💎 <b>TARIFLAR:</b>\n\n"
            f"1️⃣ Botda - {num(TARIFFS[1].price)} so'm\n"
            f"2️⃣ KANAL - {num(TARIFFS[2].price)} so'm\n"
            f"3️⃣ Bot + Kanal (10% skidka) - {num(TARIFFS[3].price)} so'm\n"
            f"4️⃣ PREMIUM VIP - {num(TARIFFS[4].price)} so'm\n\n"
            "💳 <b>TO'LOV:</b>\n\n"
            "🤖 Web App orqali avtomatik\n"
            f"⚡️ Reklama muddati: {days} kun\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [ikb("Web App ni ochish", "webapp",
                 web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
        ])
        await message.answer(pe(text), parse_mode="HTML", reply_markup=kb)

    async def handle_webapp_data(self, message: Message):
        try:
            data = json.loads(message.web_app_data.data)
            logger.info(f"WebApp: {data}")
        except Exception:
            pass

    async def handle_other(self, message: Message):
        if message.from_user.id == BOT.ADMIN_CHAT_ID:
            await message.answer(
                pe("🛡 <b>ADMIN BUYRUQLAR</b>\n\n"
                   "/admin - statistika\n"
                   "/stats - batafsil (JSON)\n"
                   "/cards - kartalar\n"
                   "/addcard - karta qo'shish (ism bilan)\n"
                   "/delcard - karta o'chirish\n"
                   "/channelid - kanal ID"),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                pe("🎮 <b>Xush kelibsiz!</b>\n\n"
                   "Boshlash uchun /start bosing"),
                parse_mode="HTML"
            )

    async def _check_subscription(self, user_id: int) -> list:
        not_sub = []
        for ch in BOT.REQUIRED_CHANNELS:
            try:
                if ch.get("type") == "invite":
                    m = await self.bot.get_chat_member(ch["id"], user_id)
                else:
                    m = await self.bot.get_chat_member(ch["username"], user_id)

                if m.status in ("left", "kicked", "banned"):
                    not_sub.append(ch)
            except Exception as e:
                logger.warning(f"Obuna tekshirish xato ({ch.get('name')}): {e}")
                not_sub.append(ch)
        return not_sub

    def _sub_kb(self, not_sub):
        btns = []
        for ch in not_sub:
            if ch.get("type") == "invite":
                url = ch["invite"]
            else:
                uname = ch["username"].replace("@", "")
                url = f"https://t.me/{uname}"
            btns.append([ikb(ch['name'], "channel", url=url)])
        btns.append([ikb("Tekshirish", "check", callback_data="check_sub")])
        return InlineKeyboardMarkup(inline_keyboard=btns)

    async def _approve_ad(self, ad_id: int, cb: CallbackQuery):
        ad = await self.db.get_ad(ad_id)
        if not ad:
            await cb.answer("❌ Topilmadi")
            return

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
                pe("✔️ <b>REKLAMANGIZ TASDIQLANDI!</b>\n\n"
                   f"📢 <b>{ad['title']}</b>\n"
                   f"🆔 #{ad_id}\n\n"
                   "🎉 Endi e'loningiz Web App'da ko'rinadi!"),
                parse_mode="HTML"
            )
        except Exception:
            pass

        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("✔️ Tasdiqlandi")
        await cb.message.answer(pe(f"✔️ <b>E'lon #{ad_id} tasdiqlandi</b>"), parse_mode="HTML")

    async def _reject_ad(self, ad_id: int, cb: CallbackQuery):
        ad = await self.db.get_ad(ad_id)
        if not ad:
            await cb.answer("❌ Topilmadi")
            return
        await self.db.update_ad_status(ad_id, "REJECTED", "Admin rad etdi")
        t = TARIFFS.get(ad["tariff"], TARIFFS[1])
        await self.db.update_balance(ad["seller_tg"], t.price, "topup", "Rad etilgan reklama qaytarildi")
        try:
            await self.bot.send_message(
                ad["seller_tg"],
                pe("❌ <b>REKLAMA RAD ETILDI</b>\n\n"
                   f"📢 <b>{ad['title']}</b>\n"
                   f"💰 Pul qaytarildi: <b>{num(t.price)} so'm</b>"),
                parse_mode="HTML"
            )
        except Exception:
            pass
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ Rad etildi")

    # ============================================================
    # KANALGA JOYLASH — PREMIUM EMOJI + QALIN SONLAR + LINKLAR
    # ============================================================
    def _tree_lines(self, items: list) -> list:
        """Ro'yxat elementlarini daraxt shaklida + qalin sonlar bilan qaytaradi."""
        out = []
        n = len(items)
        for i, item in enumerate(items):
            prefix = "└" if i == n - 1 else "├"
            out.append(f"{prefix} {bold_numbers(str(item))}")
        return out

    async def _post_to_channel(self, ad: dict):
        try:
            acc = ad.get("account_data", {}) or {}
            cur = CURRENCIES.get(ad.get("currency", "UZS"), CURRENCIES["UZS"])

            lines = [
                "🎮 <b>PUBG MOBILE AKKOUNT SOTILADI</b>",
                "",
                f"📈 <b>LVL:</b> <b>{acc.get('level', '-')}</b>",
                f"🎯 <b>Kolleksiya:</b> <b>{acc.get('collection', '-')}</b>",
                f"🏆 <b>RP:</b> {bold_numbers(str(acc.get('rp', '-')))}",
                f"👕 <b>Mifik kiyimlar:</b> <b>{acc.get('mythic_clothes', 0)}</b> ta",
            ]

            xc = acc.get("x_costume") or []
            if xc:
                lines.append("")
                lines.append("🎁 <b>X-KOSTYUM</b>")
                lines.extend(self._tree_lines(xc[:25]))

            cars = acc.get("supar_car") or []
            if cars:
                lines.append("")
                lines.append("🚗 <b>SUPAR-CAR</b>")
                lines.extend(self._tree_lines(cars[:25]))

            skins = acc.get("rare_skins") or []
            if skins:
                lines.append("")
                lines.append("💎 <b>Redkiy skinlar</b>")
                lines.extend(self._tree_lines(skins[:25]))

            guns = acc.get("guns") or []
            gc = acc.get("guns_count") or len(guns)
            if guns or gc:
                lines.append("")
                lines.append("🔫 <b>Kuchaytirilgan qurollar</b>")
                gun_items = list(guns[:24])
                if gc:
                    gun_items.append(f"Jami: {gc} ta")
                if gun_items:
                    lines.extend(self._tree_lines(gun_items))

            lines.append("")
            lines.append("")

            linked = acc.get("linked") or []
            lines.append(f"🔗 <b>Ulangan:</b> {', '.join(linked) if linked else '-'}")
            lines.append(f"🏠 <b>Manzil:</b> {ad.get('location', '-')}")
            if ad.get("full_location"):
                lines.append(f"📍 {ad['full_location']}")

            uname = (acc.get("username") or "").strip()
            phone = (acc.get("phone") or "").strip()
            if uname:
                lines.append(f"📲 <b>Tg-murojat:</b> {uname}")
            if phone:
                p = phone.replace("+", "").replace(" ", "")
                if not p.startswith("998"):
                    p = "998" + p
                lines.append(f"📞 <b>Telefon:</b> +{p}")

            lines.append("")
            lines.append("")
            if cur["symbol"] == "$":
                price_str = f"{ad['price']} $"
            else:
                price_str = f"{num(ad['price'])} {cur['symbol']}"
            lines.append(f"💰 <b>NARXI:</b> <b>{price_str}</b>")

            lines.append("")
            lines.append(BOT.CHANNEL_NOTE)
            lines.append("")
            lines.append(BOT.CHANNEL_WARNING)
            lines.append("")
            lines.append(CHANNEL_FOOTER_HTML)

            text = "\n".join(lines)

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                ikb("Reklama berish", "channel",
                    url=f"https://t.me/{BOT.USERNAME}?start=create")
            ]])

            caption = pe(text)

            if ad.get("video_file_id"):
                msg = await self.bot.send_video(
                    BOT.ADS_CHANNEL_ID, ad["video_file_id"],
                    caption=caption, parse_mode="HTML", reply_markup=kb
                )
            else:
                msg = await self.bot.send_message(
                    BOT.ADS_CHANNEL_ID, caption,
                    parse_mode="HTML", reply_markup=kb
                )
            await self.db.update_ad_status(ad["id"], "ACTIVE", channel_msg_id=msg.message_id)
            logger.info(f"#{ad['id']} reklama kanaliga joylandi (premium + bold + links)")
        except Exception as e:
            logger.error(f"Kanalga joylash xato: {e}", exc_info=True)

    async def notify_admin_new_ad(self, ad: dict):
        try:
            cur = CURRENCIES.get(ad.get("currency", "UZS"), CURRENCIES["UZS"])
            text = (
                "🆕 <b>YANGI REKLAMA</b>\n\n"
                f"📝 <b>{ad['title']}</b>\n"
                f"💰 {num(ad['price'])} {cur['symbol']} {cur['flag']}\n"
                f"📍 {ad.get('location', '-')}\n"
                f"🎯 Tarif: {ad.get('tariff')}\n"
                f"🆔 <code>{ad['id']}</code>\n\n"
                "👇 Tasdiqlaysizmi?"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                ikb("Tasdiqlash", "check", callback_data=f"approve_ad_{ad['id']}"),
                ikb("Rad etish", "cross", callback_data=f"reject_ad_{ad['id']}"),
            ]])
            caption = pe(text)
            if ad.get("video_file_id"):
                await self.bot.send_video(
                    BOT.ADMIN_CHAT_ID, ad["video_file_id"],
                    caption=caption, parse_mode="HTML", reply_markup=kb
                )
            else:
                await self.bot.send_message(
                    BOT.ADMIN_CHAT_ID, caption,
                    parse_mode="HTML", reply_markup=kb
                )
        except Exception as e:
            logger.error(f"Admin notify xato: {e}")

    async def notify_admin_vip_request(self, info: dict):
        try:
            acc = info.get("account_data", {}) or {}
            lines = [
                "👑 <b>VIP XIZMAT SO'ROVI</b>",
                "",
                f"👤 <b>Ism:</b> {info.get('first_name') or '-'} {info.get('last_name') or ''}",
                f"🆔 <b>Chat ID:</b> <code>{info.get('telegram_id')}</code>",
                f"🔗 <b>Username:</b> @{info.get('username') or '-'}",
                f"📱 <b>Telefon:</b> +998{info.get('phone') or '-'}",
                "",
                f"💰 <b>To'lov:</b> {num(info.get('price', 0))} so'm",
                f"💳 <b>Yangi balans:</b> {num(info.get('balance', 0))} so'm",
                "",
                "📋 <b>AKKAUNT MA'LUMOTLARI:</b>",
                "",
                f"📈 LVL: <b>{acc.get('level', '-')}</b>",
                f"🎯 Kolleksiya: <b>{acc.get('collection', '-')}</b>",
                f"🏆 RP: {bold_numbers(str(acc.get('rp', '-')))}",
                f"👕 Mifik: <b>{acc.get('mythic_clothes', 0)}</b> ta",
            ]
            for key, label, emoji in [
                ("x_costume", "X-KOSTYUM", "🎁"),
                ("supar_car", "SUPAR-CAR", "🚗"),
                ("rare_skins", "Redkiy skinlar", "💎"),
                ("guns", "Kuchaytirilgan qurollar", "🔫"),
            ]:
                arr = acc.get(key) or []
                if arr:
                    lines.append("")
                    lines.append(f"{emoji} <b>{label}:</b>")
                    for s in arr[:25]:
                        lines.append(f"  • {bold_numbers(str(s))}")

            lines.append("")
            lines.append(f"🏠 Manzil: {acc.get('location', '-') or '-'}")
            lines.append(f"📲 TG: {acc.get('username', '-') or '-'}")
            lines.append(f"📞 Tel: +998{acc.get('phone', '-') or '-'}")

            text = "\n".join(lines)

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                ikb("Foydalanuvchiga yozish", "message",
                    url=f"tg://user?id={info.get('telegram_id')}")
            ]])

            await self.bot.send_message(
                BOT.ADMIN_CHAT_ID, pe(text),
                parse_mode="HTML", reply_markup=kb
            )
        except Exception as e:
            logger.error(f"VIP notify: {e}", exc_info=True)

    async def send_receipt_to_admin(self, receipt_data_url: str, info: dict, completed: bool):
        try:
            header, encoded = receipt_data_url.split(",", 1)
            raw = base64.b64decode(encoded)
            photo = BufferedInputFile(raw, filename="receipt.jpg")

            if completed:
                status_text = (
                    "✔️ <b>AVTOMATIK TASDIQLANDI</b>\n"
                    "Userbot to'lovni aniqladi, balans qo'shildi"
                )
            else:
                status_text = (
                    "⏳ <b>TEKSHIRISH KERAK</b>\n"
                    "Userbot hali to'lovni aniqlamadi.\n"
                    "Admin panelda tekshiring."
                )

            caption = (
                f"🧾 <b>TO'LOV CHEKI</b>\n\n"
                f"👤 <b>Ism:</b> {info.get('user_name') or '-'}\n"
                f"📱 <b>Telefon:</b> +998 {info.get('phone') or '-'}\n"
                f"🆔 <b>ID:</b> <code>{info.get('telegram_id')}</code>\n"
                f"💰 <b>Summa:</b> {num(info.get('amount', 0))} so'm\n"
                f"📋 <b>So'rov:</b> #{info.get('request_id')}\n\n"
                f"{status_text}"
            )
            await self.bot.send_photo(
                BOT.ADMIN_CHAT_ID, photo,
                caption=pe(caption), parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"send_receipt_to_admin: {e}", exc_info=True)

    async def start(self):
        logger.info("CardinalBot v6.2 (Premium Emoji + Bold Numbers + Clickable Footer) ishga tushdi")
        await self.userbot.start()
        await self.cleaner.start()
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.cleaner.stop()
        await self.userbot.stop()
        await self.bot.session.close()
