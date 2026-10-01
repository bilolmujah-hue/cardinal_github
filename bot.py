"""
CARDINAL REKLAMA BOT v5.2
- Userbot DB orqali boshqariladi (admin panel)
- Chat yo'q, faqat reklama
- Avtomatik to'lov (userbot orqali)
- Video 7 kunda o'chadi
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


class CardinalBot:
    def __init__(self, db: Database):
        self.bot = Bot(token=BOT.TOKEN)
        self.dp = Dispatcher()
        self.db = db

        # 🔥 Userbot — DB bilan
        self.userbot = CardXabarWatcher(
            on_payment=self._on_payment_received,
            db=db
        )

        # Cleaner
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
                        f"✅ <b>To'lov qabul qilindi!</b>\n\n"
                        f"💰 Summa: <b>{amount:,} so'm</b>\n"
                        f"💳 Karta: ***{payer_last4}\n\n"
                        f"Hisobingiz to'ldirildi!",
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
                    await cb.message.answer("✅ Obuna tasdiqlandi!\n\nEndi telefon raqamingizni yuboring:",
                                            reply_markup=kb)

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
    # COMMANDS
    # ============================================================
    async def cmd_start(self, message: Message):
        u = message.from_user
        if await self.db.is_blocked(u.id):
            await message.answer("🚫 Siz botdan bloklangansiz!")
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
                "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
                + "\n".join(f"• {c['name']}" for c in BOT.REQUIRED_CHANNELS)
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
            "👋 Assalomu alaykum!\n\n"
            "🎮 <b>CARDINAL REKLAMA</b> botiga xush kelibsiz!\n\n"
            "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring.",
            parse_mode="HTML", reply_markup=kb
        )

    async def cmd_admin(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        await message.answer(
            f"🛡️ <b>ADMIN PANEL</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{s['users']}</b>\n"
            f"🚫 Bloklangan: <b>{s['blocked']}</b>\n"
            f"📢 Reklamalar: <b>{s['ads']}</b> (faol: {s['active_ads']})\n"
            f"⏳ Kutilmoqda: <b>{s['pending']}</b>\n"
            f"💳 Aktiv kartalar: <b>{s['cards']}</b>\n"
            f"⭐ Otziflar: <b>{s['feedbacks']}</b>\n"
            f"🤖 Userbot: <b>{'✅' if s.get('userbot') else '❌'}</b>\n"
            f"💵 Umumiy balans: <b>{s['total_balance']:,} so'm</b>\n"
            f"📈 30 kunlik daromad: <b>{s['monthly_income']:,} so'm</b>",
            parse_mode="HTML"
        )

    async def cmd_stats(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID:
            return
        s = await self.db.get_stats()
        await message.answer(f"<pre>{json.dumps(s, indent=2, ensure_ascii=False)}</pre>", parse_mode="HTML")

    async def cmd_channelid(self, message: Message):
        await message.answer(
            f"Chat ID: <code>{message.chat.id}</code>\nType: {message.chat.type}",
            parse_mode="HTML"
        )

    async def cmd_cards(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        cards = await self.db.get_cards(active_only=False)
        if not cards:
            await message.answer("💳 Karta yo'q. /addcard 5614... bilan qo'shing.")
            return
        lines = ["💳 <b>KARTALAR</b>\n"]
        for c in cards:
            st = "🟢" if c["is_active"] else "🔴"
            lines.append(f"{st} <code>{c['number']}</code>\n   💰 {c['total_received']:,} so'm\n")
        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_addcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Foydalanish: /addcard 5614682110725894")
            return
        num = parts[1].strip().replace(" ", "")
        if not num.isdigit() or len(num) != 16:
            await message.answer("❌ 16 xonali raqam kiriting")
            return
        ok = await self.db.add_card(num)
        await message.answer("✅ Qo'shildi" if ok else "❌ Allaqachon bor")

    async def cmd_delcard(self, message: Message):
        if message.from_user.id != BOT.ADMIN_CHAT_ID: return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Foydalanish: /delcard <card_id>")
            return
        try:
            cid = int(parts[1])
            await self.db.remove_card(cid)
            await message.answer(f"✅ Karta #{cid} o'chirildi")
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
            await message.answer("Avval kanallarga obuna bo'ling!",
                                 reply_markup=self._sub_kb(not_sub))
            return

        await self.db.get_or_create_user(
            telegram_id=u.id, username=u.username,
            first_name=u.first_name, last_name=u.last_name
        )
        await self.db.update_phone(u.id, phone)
        await message.answer("✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>", parse_mode="HTML")
        await self._show_main_menu(message)

    async def handle_profile_btn(self, message: Message):
        u = await self.db.get_user(message.from_user.id)
        if not u:
            await message.answer("❌ /start bosing"); return
        admin_label = " 🛡️ <b>ADMIN</b>" if u.get("is_admin") else ""
        text = (
            f"👤 <b>PROFIL</b>{admin_label}\n\n"
            f"🆔 ID: <code>{u['telegram_id']}</code>\n"
            f"📛 {u.get('first_name') or '-'} {u.get('last_name') or ''}\n"
            f"📱 +998{u.get('phone') or '-'}\n\n"
            f"💰 Balans: <b>{u['balance']:,} so'm</b>\n"
            f"💸 Sarflangan: <b>{u['spent']:,} so'm</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))
        ]])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    async def handle_tx_btn(self, message: Message):
        txs = await self.db.get_user_txs(message.from_user.id)
        u = await self.db.get_user(message.from_user.id)
        if not txs:
            await message.answer(f"💳 Tranzaksiya yo'q.\n\n💰 Balans: <b>{u['balance']:,} so'm</b>", parse_mode="HTML")
            return
        lines = [f"💳 <b>TRANZAKSIYALAR</b>\n\n💰 Balans: {u['balance']:,} so'm\n"]
        for tx in txs[:25]:
            sign = "+" if tx["type"] == "topup" else "-"
            emoji = "➕" if tx["type"] == "topup" else "➖"
            lines.append(f"{emoji} {sign}{tx['amount']:,} so'm — {tx['created_at'].strftime('%d.%m %H:%M')}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    async def handle_about_btn(self, message: Message):
        text = (
            "ℹ️ <b>CARDINAL REKLAMA BOT</b>\n\n"
            "🎮 PUBG Mobile akkauntlarini sotish/sotib olish platformasi.\n\n"
            "📋 <b>Tariflar:</b>\n"
            f"1️⃣ STANDART — {TARIFFS[1].price:,} so'm\n"
            f"2️⃣ KANAL + WEB APP — {TARIFFS[2].price:,} so'm\n"
            f"3️⃣ RARE (10% skidka) — {TARIFFS[3].price:,} so'm\n"
            f"4️⃣ PREMIUM VIP — {TARIFFS[4].price:,} so'm\n\n"
            "💳 To'lov Web App orqali avtomatik."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🌐 Web App", web_app=WebAppInfo(url=BOT.WEB_APP_URL))
        ]])
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
                "🛡️ Buyruqlar:\n"
                "/admin — statistika\n"
                "/cards — kartalar\n"
                "/addcard — karta qo'shish\n"
                "/delcard — karta o'chirish"
            )
        else:
            await message.answer("🎮 /start bosing")

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

    async def _show_main_menu(self, message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web App ni ochish", web_app=WebAppInfo(url=BOT.WEB_APP_URL))],
            [InlineKeyboardButton(text="📢 Kanalimiz", url=f"https://t.me/{BOT.CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton(text="👨‍💻 Admin", url=f"https://t.me/{BOT.ADMIN_USERNAME}")],
        ])
        rkb = ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(text="👤 Profilim"),
                KeyboardButton(text="💳 Tranzaksiya"),
                KeyboardButton(text="ℹ️ Bot haqida"),
            ]],
            resize_keyboard=True
        )
        await message.answer(
            "🎮 <b>CARDINAL REKLAMA</b>\n\n"
            "Web App orqali reklama joylang va akkauntlarni ko'ring.",
            parse_mode="HTML", reply_markup=kb
        )
        await message.answer("⬇️ Qo'shimcha tugmalar:", reply_markup=rkb)

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
                f"✅ Reklamangiz tasdiqlandi!\n\n📢 {ad['title']}\n🆔 #{ad_id}"
            )
        except Exception:
            pass

        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("✅ Tasdiqlandi")
        await cb.message.answer(f"✅ E'lon #{ad_id} tasdiqlandi")

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
                f"❌ Reklamangiz rad etildi.\nPul qaytarildi: {t.price:,} so'm"
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
            lines.append(f"💰 <b>NARXI: {ad['price']:,} {cur['symbol']}</b> {cur['flag']}")
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
                f"🆕 <b>YANGI REKLAMA</b>\n\n"
                f"📝 <b>{ad['title']}</b>\n"
                f"💰 {ad['price']:,} {cur['symbol']} {cur['flag']}\n"
                f"📍 {ad.get('location', '-')}\n"
                f"🎯 Tarif: {ad.get('tariff')}\n"
                f"🆔 <code>{ad['id']}</code>"
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
        logger.info("🚀 CardinalBot v5.2 ishga tushdi")
        # Userbot — DB dan yuklanadi
        await self.userbot.start()
        # Cleaner
        await self.cleaner.start()
        # Polling
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.cleaner.stop()
        await self.userbot.stop()
        await self.bot.session.close()
