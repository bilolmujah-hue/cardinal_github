"""
Cardinal Bot v5.7
- Yangi kanal formati (1-kanalga post)
- VIP maxsus oqim
- /start=create parametri
- Silent userbot
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
# HELPERS
# ============================================================
def num(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return "0"


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
    return {"APPROVED": "✅", "PENDING": "⏳", "REJECTED": "❌"}.get(status, "⚪")


def tx_type_emoji(tx_type: str):
    if tx_type == "topup":
        return "💰", "Hisob to'ldirish", "+"
    if tx_type == "spend":
        return "💸", "Reklama uchun", "−"
    if tx_type == "remove":
        return "⚠️", "Admin olib tashladi", "−"
    return "💳", "Boshqa", ""


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

    # ============================================================
    # SILENT PAYMENT
    # ============================================================
    async def _on_payment_received(self, amount: int, payer_last4: str, raw: str) -> dict:
        """Userbot xabar o'qidi. Silent — xabar YUBORMAYMIZ."""
        try:
            result = await self.db.match_payment(amount, payer_last4)
            if result and result.get("ok"):
                logger.info(f"✅ To'lov aniqlandi: {amount} so'm (***{payer_last4}) — silent")
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
                "🚫 <b>Siz botdan bloklangansiz!</b>\n\n"
                "Savol uchun admin bilan bog'laning.",
                parse_mode="HTML"
            )
            return

        await self.db.get_or_create_user(
            telegram_id=u.id, username=u.username,
            first_name=u.first_name, last_name=u.last_name
        )

        # 🔥 /start=create — Web App'ni reklama berish sahifasida ochish
        args = message.text.split(maxsplit=1)
        if len(args) > 1 and args[1].strip() == "create":
            if await self.db.is_registered(u.id):
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🌐 Reklama berish",
                        web_app=WebAppInfo(url=BOT.WEB_APP_URL + "?open=create")
                    )
                ]])
                await message.answer(
                    "📢 <b>REKLAMA BERISH</b>\n\n"
                    "Quyidagi tugmani bosing va tarifni tanlang:",
                    parse_mode="HTML", reply_markup=kb
                )
                return

        if await self.db.is_registered(u.id):
            await self._show_main_menu(message)
            return

        not_sub = await self._check_subscription(u.id)
        if not_sub:
            await message.answer(
                "📢 <b>KANALLARGA OBUNA BO'LING</b>\n"
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
            f" <b>ASSALOMU ALAYKUM {u.first_name}</b> 🤝\n"
            " <b>CARDINAL AKKAUNT</b> —  Orqali Pubg mobile, akkauntingizni ishonchli sotasiz va sotib olasiz! 😊\n\n"
            "📌 <b>Ro'yxatdan o'tish uchun</b>\n"
            "pastdagi <b>📞 Raqamni yuborish</b> tugmasini bosing.",
            parse_mode="HTML", reply_markup=kb
        )

    async def _show_main_menu(self, message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
            [InlineKeyboardButton(text="📢 Asosiy kanal", url=BOT.ADS_CHANNEL_INVITE)],
            [InlineKeyboardButton(
                text="📢 " + BOT.PUBLIC_CHANNEL_NAME,
                url=f"https://t.me/{BOT.PUBLIC_CHANNEL_USERNAME.replace('@','')}"
            )],
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
            "🎮 <b>CARDINAL AKKAUNT</b>\n\n"
            "💎 <b>Premium xizmat:</b>\n"
            "  •  Video reklama joylash\n"
            "  •  Akkaunt sotish va sotib olish\n"
            "  •  Balansni avtomatik to'ldirish\n"
            "  •  Otzif qoldirish\n\n"
            "🚀 Web App orqali barcha imkoniyatlar!",
            parse_mode="HTML", reply_markup=kb
        )
        await message.answer(
            "⬇️ <b>Qo'shimcha bo'limlar:</b>",
            parse_mode="HTML", reply_markup=rkb
        )

    async def cmd_admin(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        days = await self.db.get_ad_days()
        await message.answer(
            "🛡️ <b>ADMIN PANEL</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{num(s['users'])}</b>\n"
            f"🚫 Bloklangan: <b>{num(s['blocked'])}</b>\n"
            f"📢 Reklamalar: <b>{num(s['ads'])}</b>\n"
            f"🟢 Faol: <b>{num(s['active_ads'])}</b>\n"
            f"⏳ Kutilmoqda: <b>{num(s['pending'])}</b>\n"
            f"💳 Aktiv kartalar: <b>{num(s['cards'])}</b>\n"
            f"⭐ Otziflar: <b>{num(s['feedbacks'])}</b>\n"
            f"🤖 Userbot: <b>{'✅ Aktiv' if s.get('userbot') else '❌ Yoq'}</b>\n"
            f"📅 Reklama muddati: <b>{days} kun</b>\n\n"
            f"💵 Umumiy balans: <b>{num(s['total_balance'])} so'm</b>\n"
            f"📈 30 kunlik daromad: <b>{num(s['monthly_income'])} so'm</b>",
            parse_mode="HTML"
        )

    async def cmd_stats(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        await message.answer(f"<pre>{json.dumps(s, indent=2, ensure_ascii=False)}</pre>", parse_mode="HTML")

    async def cmd_channelid(self, message: Message):
        await message.answer(
            f"🆔 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
            f"📁 <b>Type:</b> {message.chat.type}",
            parse_mode="HTML"
        )

    async def cmd_cards(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        cards = await self.db.get_cards(active_only=False)
        if not cards:
            await message.answer(
                "💳 <b>KARTALAR</b>\n\n"
                "❌ Karta yo'q\n\n"
                "➕ Qo'shish: <code>/addcard 5614682110725894 Ism Familiya</code>",
                parse_mode="HTML"
            )
            return
        lines = ["💳 <b>KARTALAR</b>\n\n"]
        for i, c in enumerate(cards, 1):
            st = "🟢" if c["is_active"] else "🔴"
            holder = c.get("holder") or "—"
            lines.append(
                f"{st} <b>#{i}</b> · <code>{c['number']}</code>\n"
                f"     👤 {holder}\n"
                f"     💰 {num(c['total_received'])} so'm yig'ildi\n"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_addcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "💳 <b>Karta qo'shish</b>\n\n"
                "Format: <code>/addcard 5614682110725894 Ism Familiya</code>",
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
            "✅ <b>Qo'shildi</b>" if ok else "❌ Xatolik",
            parse_mode="HTML"
        )

    async def cmd_delcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
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
            "✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n\n"
            "🎉 Endi siz platformadan to'liq foydalanishingiz mumkin!",
            parse_mode="HTML"
        )
        await self._show_main_menu(message)

    # ============================================================
    # PROFILE
    # ============================================================
    async def handle_profile_btn(self, message: Message):
        u = await self.db.get_user(message.from_user.id)
        if not u:
            await message.answer("❌ /start bosing")
            return

        admin_label = " 🛡️ <b>ADMIN</b>" if u.get("is_admin") else ""
        status_emoji_ = "🟢" if not u.get("is_blocked") else "🔴"
        status_text = "Faol" if not u.get("is_blocked") else "Bloklangan"

        async with self.db.pool.acquire() as c:
            total_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1", u["id"])
            active_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='ACTIVE'", u["id"])
            pending_ads = await c.fetchval("SELECT COUNT(*) FROM ads WHERE user_id=$1 AND status='PENDING'", u["id"])

        text = 
            f"👤 <b>PROFILINGIZ</b>{admin_label}\n\n"
            f"🆔 <b>ID:</b> <code>{u['telegram_id']}</code>\n"
            f"📛 <b>Ism:</b> {u.get('first_name') or '-'}\n"
            f"📛 <b>Familiya:</b> {u.get('last_name') or '-'}\n"
            f"🔗 <b>Username:</b> @{u.get('username') or '-'}\n"
            f"📱 <b>Telefon:</b> +998{u.get('phone') or '-'}\n\n"
            f"💰 <b>Balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Sarflangan:</b> {num(u['spent'])} so'm\n\n"
            f"📢 <b>Reklamalar:</b>\n"
            f"  • 📊 Jami: <b>{total_ads}</b>\n"
            f"  • 🟢 Faol: <b>{active_ads}</b>\n"
            f"  • 🟡 Kutilmoqda: <b>{pending_ads}</b>\n\n"
            f"📅 Ro'yxatdan: <b>{fmt_date(u.get('created_at'))}</b>\n"
            f"📊 Holat: {status_emoji_} <b>{status_text}</b>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    # ============================================================
    # TRANZAKSIYALAR
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
                "💳 <b>TRANZAKSIYALAR</b>\n\n"
                "😔 Hozircha tranzaksiyalar yo'q\n\n"
                f"💰 Joriy balans: <b>{num(u['balance'])} so'm</b>\n\n"
                "💡 Hisobni to'ldirish uchun:\n"
                "🌐 Web App → Hisobni to'ldirish",
                parse_mode="HTML"
            )
            return

        header = (
            f"💳 <b>TRANZAKSIYALAR TARIXI</b>\n\n"
            f"💰 <b>Joriy balans:</b> {num(u['balance'])} so'm\n"
            f"💸 <b>Jami sarflangan:</b> {num(u['spent'])} so'm\n"
            f"📊 <b>Oxirgi {len(txs)} ta tranzaksiya</b>\n"
            f"\n\n"
        )

        lines = [header]
        for tx in txs:
            emoji, label, sign = tx_type_emoji(tx["type"])
            st_emoji = status_emoji(tx["status"])
            amount = tx["amount"]
            date_str = fmt_date(tx["created_at"], full=True)
            desc = (tx.get("description") or "")[:40]

            if sign in ("+", "−"):
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

        lines.append(
            "💡 <i>Har bir to'lov avtomatik tasdiqlanadi</i>"
        )

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
                await message.answer(chunk, parse_mode="HTML")
                await asyncio.sleep(0.3)
        else:
            await message.answer(text, parse_mode="HTML")

    # ============================================================
    # BOT HAQIDA
    # ============================================================
    async def handle_about_btn(self, message: Message):
        days = await self.db.get_ad_days()
        text = (
            "ℹ️ <b>BOT HAQIDA</b>\n\n"
            "🎮 <b>CARDINAL AKKAUNT</b>\n"
            "PUBG Mobile akkauntlarini sotish va sotib olish uchun premium platforma.\n\n"
            "✨ <b>IMKONIYATLAR:</b>\n\n"
            "📹 Video reklama (10 daqiqagacha)\n"
            "🛒 Akkaunt sotib olish\n"
            "❤️ Saqlangan akkauntlar\n"
            "⭐ Otzif qoldirish\n"
            "💰 Avtomatik balans to'ldirish\n"
            "🛡️ Xavfsiz va ishonchli\n\n"
            "💎 <b>TARIFLAR:</b>\n\n"
            f"1️⃣ Botda — {num(TARIFFS[1].price)} so'm\n"
            f"2️⃣ KANAL — {num(TARIFFS[2].price)} so'm\n"
            f"3️⃣ Bot + Kanal(10% skidka) — {num(TARIFFS[3].price)} so'm\n"
            f"4️⃣ PREMIUM VIP — {num(TARIFFS[4].price)} so'm\n\n"
            "💳 <b>TO'LOV:</b>\n\n"
            "🤖 Web App orqali avtomatik\n"
            f"⚡ Reklama muddati: {days} kun\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
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
                "/addcard — karta qo'shish (ism bilan)\n"
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
            btns.append([InlineKeyboardButton(
                text=f"📢 {ch['name']}",
                url=url
            )])
        btns.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
        return InlineKeyboardMarkup(inline_keyboard=btns)

    # ============================================================
    # ADMIN APPROVE / REJECT
    # ============================================================
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
                "✅ <b>REKLAMANGIZ TASDIQLANDI!</b>\n\n"
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
            await cb.answer("❌ Topilmadi")
            return
        await self.db.update_ad_status(ad_id, "REJECTED", "Admin rad etdi")
        t = TARIFFS.get(ad["tariff"], TARIFFS[1])
        await self.db.update_balance(ad["seller_tg"], t.price, "topup", "Rad etilgan reklama qaytarildi")
        try:
            await self.bot.send_message(
                ad["seller_tg"],
                "❌ <b>REKLAMA RAD ETILDI</b>\n\n"
                f"📢 <b>{ad['title']}</b>\n"
                f"💰 Pul qaytarildi: <b>{num(t.price)} so'm</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ Rad etildi")

    # ============================================================
    # KANALGA JOYLASH — FAQAT 1-KANAL, YANGI FORMAT
    # ============================================================
    async def _post_to_channel(self, ad: dict):
        """Faqat 1-kanalga (ADS_CHANNEL_ID) yangi formatda post qiladi."""
        try:
            acc = ad.get("account_data", {}) or {}
            cur = CURRENCIES.get(ad.get("currency", "UZS"), CURRENCIES["UZS"])

            lines = [
                "🎮 <b>PUBG MOBILE AKKOUNT SOTILADI</b>",
                "",
                f"📈 <b>LVL:</b> {acc.get('level', '-')}",
                f"🎯 <b>Kolleksiya:</b> {acc.get('collection', '-')}",
                f"🏆 <b>RP:</b> {acc.get('rp', '-')}",
                f"👕 <b>Mifik kiyimlar:</b> {acc.get('mythic_clothes', 0)} ta",
            ]

            # X-KOSTYUM
            xc = acc.get("x_costume") or []
            if xc:
                lines.append("")
                lines.append("🎁 <b>X-KOSTYUM:</b>")
                for s in xc[:25]:
                    lines.append(f"  • {s}")

            # SUPAR-CAR
            cars = acc.get("supar_car") or []
            if cars:
                lines.append("")
                lines.append("🚗 <b>SUPAR-CAR:</b>")
                for s in cars[:25]:
                    lines.append(f"  • {s}")

            # Redkiy skinlar
            skins = acc.get("rare_skins") or []
            if skins:
                lines.append("")
                lines.append("💎 <b>Redkiy skinlar:</b>")
                for s in skins[:25]:
                    lines.append(f"  • {s}")

            # Kuchaytirilgan qurollar
            guns = acc.get("guns") or []
            gc = acc.get("guns_count") or len(guns)
            lines.append("")
            lines.append("🔫 <b>Kuchaytirilgan qurollar:</b>")
            for g in guns[:25]:
                lines.append(f"  • {g}")
            if gc:
                lines.append(f"  • Jami kuchaytiriladigan qurollar {gc} ta")

            # Ulangan
            linked = acc.get("linked") or []
            lines.append("")
            lines.append(f"🔗 <b>Ulangan:</b> {', '.join(linked) if linked else '-'}")
            lines.append(f"🏠 <b>Manzil:</b> {ad.get('location', '-')}")
            if ad.get("full_location"):
                lines.append(f"📍 {ad['full_location']}")

            # Aloqa
            uname = (acc.get("username") or "").strip()
            phone = (acc.get("phone") or "").strip()
            if uname:
                lines.append(f"📲 <b>Tg-murojat:</b> {uname}")
            if phone:
                p = phone.replace("+", "").replace(" ", "")
                if not p.startswith("998"):
                    p = "998" + p
                lines.append(f"📞 <b>Telefon raqam:</b> +{p}")

            # Narx
            if cur["symbol"] == "$":
                price_str = f"{ad['price']} $ {cur['flag']}"
            else:
                price_str = f"{num(ad['price'])} {cur['symbol']} {cur['flag']}"
            lines.append(f"💰 <b>NARXI:</b> {price_str}")

            # Doimiy matnlar
            lines.append("")
            lines.append(BOT.CHANNEL_NOTE)
            lines.append("")
            lines.append(BOT.CHANNEL_WARNING)
            lines.append("")
            lines.append(BOT.CHANNEL_FOOTER)

            text = "\n".join(lines)

            # Tugma: botga o'tib avtomatik /start=create
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="📢 Reklama berish",
                    url=f"https://t.me/{BOT.USERNAME}?start=create"
                )
            ]])

            if ad.get("video_file_id"):
                msg = await self.bot.send_video(
                    BOT.ADS_CHANNEL_ID, ad["video_file_id"],
                    caption=text, parse_mode="HTML", reply_markup=kb
                )
            else:
                msg = await self.bot.send_message(
                    BOT.ADS_CHANNEL_ID, text,
                    parse_mode="HTML", reply_markup=kb
                )
            await self.db.update_ad_status(ad["id"], "ACTIVE", channel_msg_id=msg.message_id)
            logger.info(f"📢 #{ad['id']} reklama kanaliga joylandi")
        except Exception as e:
            logger.error(f"Kanalga joylash xato: {e}", exc_info=True)

    # ============================================================
    # ADMIN NOTIFY — YANGI REKLAMA
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
    # VIP XIZMAT SO'ROVI — YANGI
    # ============================================================
    async def notify_admin_vip_request(self, info: dict):
        """VIP tarif tanlanganda adminga to'liq ma'lumot yuborish."""
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
                f"📈 LVL: {acc.get('level', '-')}",
                f"🎯 Kolleksiya: {acc.get('collection', '-')}",
                f"🏆 RP: {acc.get('rp', '-')}",
                f"👕 Mifik: {acc.get('mythic_clothes', 0)} ta",
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
                        lines.append(f"  • {s}")

            lines.append("")
            lines.append(f"🏠 Manzil: {acc.get('location', '-') or '-'}")
            lines.append(f"📲 TG: {acc.get('username', '-') or '-'}")
            lines.append(f"📞 Tel: +998{acc.get('phone', '-') or '-'}")

            text = "\n".join(lines)

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="💬 Foydalanuvchiga yozish",
                    url=f"tg://user?id={info.get('telegram_id')}"
                )
            ]])

            await self.bot.send_message(
                BOT.ADMIN_CHAT_ID, text,
                parse_mode="HTML", reply_markup=kb
            )
        except Exception as e:
            logger.error(f"VIP notify: {e}", exc_info=True)

    # ============================================================
    # RECEIPT
    # ============================================================
    async def send_receipt_to_admin(self, receipt_data_url: str, info: dict, completed: bool):
        try:
            header, encoded = receipt_data_url.split(",", 1)
            raw = base64.b64decode(encoded)
            photo = BufferedInputFile(raw, filename="receipt.jpg")

            if completed:
                status_text = (
                    "✅ <b>AVTOMATIK TASDIQLANDI</b>\n"
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
                caption=caption, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"send_receipt_to_admin: {e}", exc_info=True)

    # ============================================================
    # START
    # ============================================================
    async def start(self):
        logger.info("🚀 CardinalBot v5.7 ishga tushdi")
        await self.userbot.start()
        await self.cleaner.start()
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.cleaner.stop()
        await self.userbot.stop()
        await self.bot.session.close()
