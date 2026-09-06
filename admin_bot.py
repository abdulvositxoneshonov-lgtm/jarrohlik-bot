"""
Jarrohlik Markazi — Admin Bot
Bu ALOHIDA bot — faqat adminlar uchun. Mijozlar bilan bog'liq bot.py'dan mustaqil ishlaydi,
lekin bir xil bazani (database.py) ishlatadi, shuning uchun ikkalasi ham bir xil
ma'lumotlarni ko'radi/o'zgartiradi.

Ishga tushirish: python admin_bot.py (bot.py bilan bir vaqtda, alohida terminalda)
"""

import logging
import os
import asyncio
import io
import uuid
import html
from collections import Counter
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from flask import Flask
from database import db, User, Service, Booking, FAQ, BookingStatus, QuickLink, ClinicInfo, BroadcastMessage

# ==================== SOZLAMALAR ====================

load_dotenv()

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().lstrip("-").isdigit()
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation holatlari
(
    ADMIN_MENU, SVC_NAME, SVC_DESC, SVC_DURATION, SVC_PRICE, SVC_EDIT_VALUE, FAQ_Q, FAQ_A, FAQ_CAT,
    CLINIC_EDIT_VALUE, CLINIC_LOCATION, BROADCAST_HEADLINE, BROADCAST_TEXT, BROADCAST_IMAGE,
    APPOINTMENT_DATE,
) = range(15)

# Rasm biriktirilgan ommaviy xabarlar shu papkaga saqlanadi — bot.py xuddi shu papkadan o'qib qayta yuklaydi
# (Telegram file_id turli botlar orasida ishlamaydi, shuning uchun rasm fayl sifatida saqlanadi)
BROADCAST_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "broadcast_images")
os.makedirs(BROADCAST_IMAGES_DIR, exist_ok=True)

CLINIC_FIELDS = {
    "address": "Manzil",
    "phone": "Telefon",
    "working_hours": "Ish vaqti",
}

STATUS_EMOJI = {
    BookingStatus.PENDING: "🟡",
    BookingStatus.CONFIRMED: "🟢",
    BookingStatus.CANCELLED: "🔴",
    BookingStatus.COMPLETED: "✅",
}

STATUS_LABEL = {
    BookingStatus.PENDING: "Kutilmoqda",
    BookingStatus.CONFIRMED: "Tasdiqlangan",
    BookingStatus.CANCELLED: "Bekor qilingan",
    BookingStatus.COMPLETED: "Bajarilgan",
}

# Filtr kaliti -> (chiroyli nomi, DB status yoki None="barchasi")
BOOKING_FILTERS = {
    "all": ("📋 Barchasi", None),
    "pending": ("🟡 Kutilayotgan", BookingStatus.PENDING),
    "confirmed": ("🟢 Tasdiqlangan", BookingStatus.CONFIRMED),
    "cancelled": ("🔴 Bekor qilingan", BookingStatus.CANCELLED),
    "completed": ("✅ Bajarilgan", BookingStatus.COMPLETED),
}

SVC_FIELDS = {
    "name": "Nomi",
    "description": "Tavsif",
    "duration_minutes": "Davomiyligi (daqiqa)",
    "price": "Narxi (so'm)",
}

# Bot.py bilan BIR XIL bazaga ulanadi
flask_app = Flask(__name__)
flask_app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(flask_app)

with flask_app.app_context():
    db.create_all()


# ==================== YORDAMCHI FUNKSIYALAR ====================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Bookinglar", callback_data="adm_bookings"),
         InlineKeyboardButton("🏥 Xizmatlar", callback_data="adm_services")],
        [InlineKeyboardButton("❓ FAQ", callback_data="adm_faq"),
         InlineKeyboardButton("📊 Statistika", callback_data="adm_stats")],
        [InlineKeyboardButton("📍 Kontaktlar", callback_data="adm_contact"),
         InlineKeyboardButton("📢 Xabar yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📤 Eksport (CSV)", callback_data="adm_export")],
        [InlineKeyboardButton("🚪 Chiqish", callback_data="adm_exit")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== CONVERSATION HANDLERLAR ====================

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/start yoki /admin — faqat ADMIN_IDS ro'yxatidagilar uchun."""
    tg_user = update.effective_user

    if not is_admin(tg_user.id):
        await update.message.reply_text(
            f"⛔ Sizda admin huquqi yo'q.\n\n"
            f"Sizning Telegram ID: {tg_user.id}\n\n"
            f"Admin bo'lish uchun bu ID'ni .env faylidagi ADMIN_IDS ro'yxatiga qo'shing "
            f"(masalan: ADMIN_IDS={tg_user.id})."
        )
        return ConversationHandler.END

    await update.message.reply_text("🔧 Jarrohlik Markazi — Admin Panel", reply_markup=admin_main_keyboard())
    return ADMIN_MENU


async def show_admin_services(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    with flask_app.app_context():
        services = Service.query.all()

    keyboard = []
    for s in services:
        keyboard.append([
            InlineKeyboardButton(f"✏️ {s.name}", callback_data=f"asvc_edit_{s.id}"),
            InlineKeyboardButton("🗑", callback_data=f"asvc_delete_{s.id}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ Yangi xizmat", callback_data="asvc_add")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")])

    await query.edit_message_text("🏥 Xizmatlar ro'yxati:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def show_admin_faq(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    with flask_app.app_context():
        faqs = FAQ.query.all()

    keyboard = []
    for f in faqs:
        short_q = f.question if len(f.question) <= 35 else f.question[:32] + "..."
        keyboard.append([
            InlineKeyboardButton(f"❓ {short_q}", callback_data=f"faq_noop_{f.id}"),
            InlineKeyboardButton("🗑", callback_data=f"faq_delete_{f.id}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ Yangi FAQ", callback_data="faq_add")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")])

    await query.edit_message_text("❓ FAQ ro'yxati:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def show_bookings_filter_menu(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bookinglarni holati bo'yicha filtrlash menyusi."""
    with flask_app.app_context():
        total = Booking.query.count()
        pending = Booking.query.filter_by(status=BookingStatus.PENDING).count()
        confirmed = Booking.query.filter_by(status=BookingStatus.CONFIRMED).count()
        cancelled = Booking.query.filter_by(status=BookingStatus.CANCELLED).count()
        completed = Booking.query.filter_by(status=BookingStatus.COMPLETED).count()

    text = (
        "📋 <b>Bookinglar</b>\n\n"
        f"Jami: <b>{total}</b> ta\n\n"
        "Qaysi bo'limni ko'rmoqchisiz?"
    )
    keyboard = [
        [InlineKeyboardButton(f"📋 Barchasi ({total})", callback_data="bkf_all")],
        [InlineKeyboardButton(f"🟡 Kutilayotgan ({pending})", callback_data="bkf_pending")],
        [InlineKeyboardButton(f"🟢 Tasdiqlangan ({confirmed})", callback_data="bkf_confirmed")],
        [InlineKeyboardButton(f"🔴 Bekor qilingan ({cancelled})", callback_data="bkf_cancelled")],
        [InlineKeyboardButton(f"✅ Bajarilgan ({completed})", callback_data="bkf_completed")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def show_bookings_list(query, context: ContextTypes.DEFAULT_TYPE, filter_key: str) -> int:
    """Tanlangan filtrga mos bookinglarni bosiladigan kartalar (tugmalar) sifatida ko'rsatadi."""
    label, status = BOOKING_FILTERS.get(filter_key, BOOKING_FILTERS["all"])

    with flask_app.app_context():
        base_q = Booking.query
        if status is not None:
            base_q = base_q.filter_by(status=status)
        total_count = base_q.count()
        bookings = base_q.order_by(Booking.id.desc()).limit(25).all()

        keyboard = []
        last_date = None
        for b in bookings:
            date_str = b.created_at.strftime("%d.%m.%Y")
            if date_str != last_date:
                keyboard.append([InlineKeyboardButton(f"── 📅 {date_str} ──", callback_data="noop")])
                last_date = date_str
            name = b.user.full_name or b.user.first_name or "Foydalanuvchi"
            svc = b.service.name if b.service else "?"
            time_str = b.created_at.strftime("%H:%M")
            emoji = STATUS_EMOJI.get(b.status, "⚪")
            btn_text = f"{emoji} {time_str} · {name} · {svc}"
            if len(btn_text) > 60:
                btn_text = btn_text[:57] + "..."
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"bk_view_{b.id}")])

    if total_count:
        keyboard.append([InlineKeyboardButton(
            f"🧹 Ushbu ro'yxatni tozalash ({total_count} ta)", callback_data=f"bk_bulkdel_{filter_key}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_bookings")])

    shown = len(bookings)
    if not total_count:
        text = f"{label}\n\nBu bo'limda hozircha bookinglar yo'q."
    elif total_count > shown:
        text = f"{label}\n\n{total_count} ta booking topildi (so'nggi {shown} tasi ko'rsatilmoqda):"
    else:
        text = f"{label}\n\n{total_count} ta booking topildi:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def show_booking_detail(query, context: ContextTypes.DEFAULT_TYPE, booking_id: int) -> int:
    """Bitta booking haqida to'liq, chiroyli formatlangan karta — status o'zgartirish va o'chirish tugmalari bilan."""
    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b:
            await query.answer("Booking topilmadi!", show_alert=True)
            return await show_bookings_filter_menu(query, context)

        emoji = STATUS_EMOJI.get(b.status, "⚪")
        status_label = STATUS_LABEL.get(b.status, b.status.value)
        username_line = f"@{b.user.username}" if b.user.username else "username yo'q"
        current_status = b.status

        text = (
            f"📋 <b>Booking #{b.id}</b>\n"
            f"{emoji} <b>{status_label}</b>\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
            f"👤 <b>Mijoz:</b> {b.user.full_name or b.user.first_name}\n"
            f"📱 <b>Telefon:</b> {b.user.phone or '—'}\n"
            f"💬 <b>Telegram:</b> {username_line}\n\n"
            f"🏥 <b>Xizmat:</b> {b.service.name if b.service else '—'}\n"
            f"⏱ <b>Davomiyligi:</b> {b.service.duration_minutes if b.service else '—'} daqiqa\n"
            f"💰 <b>Narxi:</b> {b.service.price:,.0f} so'm\n\n"
            f"📅 <b>Yaratilgan:</b> {b.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"🆔 <b>Foydalanuvchi ID:</b> {b.user.telegram_id}"
        )
        if b.appointment_at:
            text += f"\n🗓 <b>Qabul vaqti:</b> {b.appointment_at.strftime('%d.%m.%Y %H:%M')}"
        if b.rating:
            text += f"\n⭐ <b>Mijoz bahosi:</b> {'⭐' * b.rating} ({b.rating}/5)"

    status_row = []
    if current_status != BookingStatus.CONFIRMED:
        status_row.append(InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"bk_status_confirmed_{b.id}"))
    if current_status != BookingStatus.CANCELLED:
        status_row.append(InlineKeyboardButton("❌ Bekor qilish", callback_data=f"bk_status_cancelled_{b.id}"))

    keyboard = []
    if status_row:
        keyboard.append(status_row)
    if current_status != BookingStatus.COMPLETED:
        keyboard.append([InlineKeyboardButton("✔️ Bajarildi deb belgilash", callback_data=f"bk_status_completed_{b.id}")])
    # Faqat tasdiqlangan bookinglar uchun qabul sanasini belgilash mumkin — shundagina
    # bot.py'dagi eslatma workeri 24 soat/1 soat oldin avtomatik eslatma yubora oladi
    if current_status == BookingStatus.CONFIRMED:
        keyboard.append([InlineKeyboardButton("📅 Qabul sanasini belgilash", callback_data=f"bk_setdate_{b.id}")])
    keyboard.append([InlineKeyboardButton("🗑 O'chirish", callback_data=f"bk_delete_{b.id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Ro'yxatga qaytish", callback_data="bk_backlist")])

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def change_booking_status(query, context: ContextTypes.DEFAULT_TYPE, new_status_value: str, booking_id: int) -> int:
    """Booking statusini admin panel ichidan o'zgartiradi (mijozga avtomatik xabar bormaydi — buni faqat mijozlar boti qila oladi)."""
    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b:
            await query.answer("Booking topilmadi!", show_alert=True)
            return await show_bookings_filter_menu(query, context)
        b.status = BookingStatus(new_status_value)
        db.session.commit()

    await query.answer("✅ Status yangilandi!", show_alert=False)
    return await show_booking_detail(query, context, booking_id)


async def ask_appointment_date(query, context: ContextTypes.DEFAULT_TYPE, booking_id: int) -> int:
    """'📅 Qabul sanasini belgilash' tugmasi bosilganda — sanani matn shaklida so'raydi."""
    context.user_data["setdate_booking_id"] = booking_id
    keyboard = [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data=f"bk_view_{booking_id}")]]
    await query.edit_message_text(
        "📅 Qabul sanasi va vaqtini kiriting.\n\n"
        "Format: <code>KK.OO.YYYY SS:DD</code>\n"
        "Masalan: <code>25.12.2026 14:30</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return APPOINTMENT_DATE


async def appointment_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin kiritgan sanani parse qilib bookingga yozadi — bot.py'dagi eslatma workeri shundan foydalanadi."""
    booking_id = context.user_data.get("setdate_booking_id")
    text = (update.message.text or "").strip()

    if not booking_id:
        await update.message.reply_text("Xatolik: qaysi booking ekanligi aniqlanmadi. Qaytadan urinib ko'ring.")
        return ADMIN_MENU

    try:
        appointment_at = datetime.strptime(text, "%d.%m.%Y %H:%M")
    except ValueError:
        keyboard = [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data=f"bk_view_{booking_id}")]]
        await update.message.reply_text(
            "Format noto'g'ri. Iltimos, aynan shu ko'rinishda yozing:\n"
            "<code>25.12.2026 14:30</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return APPOINTMENT_DATE

    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b:
            await update.message.reply_text("Booking topilmadi.")
            return ADMIN_MENU
        b.appointment_at = appointment_at
        # Sana qayta belgilansa (masalan ko'chirilsa) — eslatmalar yangi vaqt bo'yicha QAYTA yuborilishi uchun tiklaymiz
        b.reminder_24h_sent = False
        b.reminder_1h_sent = False
        db.session.commit()

    keyboard = [[InlineKeyboardButton("⬅️ Bookingga qaytish", callback_data=f"bk_view_{booking_id}")]]
    await update.message.reply_text(
        f"✅ Qabul sanasi belgilandi: <b>{appointment_at.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        "Mijozga 24 soat va 1 soat qolganda avtomatik eslatma yuboriladi.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ADMIN_MENU


async def confirm_booking_delete(query, context: ContextTypes.DEFAULT_TYPE, booking_id: int) -> int:
    """Bitta bookingni o'chirishdan oldin tasdiqlash so'raydi."""
    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b:
            await query.answer("Booking topilmadi!", show_alert=True)
            return await show_bookings_filter_menu(query, context)
        name = b.user.full_name or b.user.first_name or "?"
        svc = b.service.name if b.service else "?"

    keyboard = [
        [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"bk_delconfirm_{booking_id}")],
        [InlineKeyboardButton("❌ Yo'q", callback_data=f"bk_view_{booking_id}")],
    ]
    await query.edit_message_text(
        f"«{name} — {svc}» bookingini butunlay o'chirishni tasdiqlaysizmi?\nBu amalni orqaga qaytarib bo'lmaydi!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MENU


async def delete_booking(query, context: ContextTypes.DEFAULT_TYPE, booking_id: int) -> int:
    """Bitta bookingni bazadan butunlay o'chiradi."""
    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if b:
            db.session.delete(b)
            db.session.commit()

    await query.answer("🗑 O'chirildi!", show_alert=True)
    filter_key = context.user_data.get("bk_filter", "all")
    return await show_bookings_list(query, context, filter_key)


async def confirm_bulk_delete(query, context: ContextTypes.DEFAULT_TYPE, filter_key: str) -> int:
    """Filtrga mos bookinglarni ommaviy o'chirishdan oldin tasdiqlash so'raydi."""
    label, status = BOOKING_FILTERS.get(filter_key, BOOKING_FILTERS["all"])
    with flask_app.app_context():
        q = Booking.query
        if status is not None:
            q = q.filter_by(status=status)
        count = q.count()

    if count == 0:
        await query.answer("Bu bo'limda o'chiriladigan booking yo'q.", show_alert=True)
        return await show_bookings_list(query, context, filter_key)

    keyboard = [
        [InlineKeyboardButton(f"✅ Ha, {count} tasini o'chirish", callback_data=f"bk_bulkdelconfirm_{filter_key}")],
        [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data=f"bkf_{filter_key}")],
    ]
    await query.edit_message_text(
        f"⚠️ {label} bo'limidagi <b>{count} ta</b> bookingni BUTUNLAY o'chirishni tasdiqlaysizmi?\n\n"
        "Bu amalni orqaga qaytarib bo'lmaydi!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MENU


async def bulk_delete_bookings(query, context: ContextTypes.DEFAULT_TYPE, filter_key: str) -> int:
    """Filtrga mos barcha bookinglarni bazadan o'chiradi."""
    label, status = BOOKING_FILTERS.get(filter_key, BOOKING_FILTERS["all"])
    with flask_app.app_context():
        q = Booking.query
        if status is not None:
            q = q.filter_by(status=status)
        bookings = q.all()
        deleted = len(bookings)
        for b in bookings:
            db.session.delete(b)
        db.session.commit()

    await query.answer(f"🧹 {deleted} ta booking o'chirildi!", show_alert=True)
    return await show_bookings_filter_menu(query, context)


async def export_bookings_csv(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Barcha bookinglarni haqiqiy .xlsx (Excel) faylga eksport qiladi.

    CSV o'rniga xlsx ishlatiladi — chunki CSV formatida Excel foydalanuvchi kompyuterining
    til/hudud sozlamalariga qarab ustun ajratuvchisini, raqamlarni (telefon "3,5E+11" bo'lib
    qolishi) va UTF-8 belgilarni (emoji, kirill) noto'g'ri talqin qilib chalkashtirib yuborishi
    mumkin. Xlsx formatida har bir katak turi (matn/raqam/sana) aniq belgilangani uchun bunday
    muammo umuman bo'lmaydi.
    """
    with flask_app.app_context():
        bookings = Booking.query.order_by(Booking.id.desc()).all()
        rows = []
        for b in bookings:
            rows.append((
                b.id,
                b.user.full_name or b.user.first_name or "",
                b.user.phone or "",
                b.service.name if b.service else "",
                int(b.service.price) if b.service else 0,
                STATUS_LABEL.get(b.status, b.status.value),
                b.created_at,
            ))

    if not rows:
        await query.answer("Eksport qilish uchun bookinglar yo'q.", show_alert=True)
        return ADMIN_MENU

    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Bookinglar"

    headers = ["ID", "Mijoz", "Telefon", "Xizmat", "Narxi (so'm)", "Status", "Sana"]
    ws.append(headers)
    header_fill = PatternFill(start_color="1F6F5C", end_color="1F6F5C", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append(row)

    last_row = ws.max_row
    for r in range(2, last_row + 1):
        ws.cell(row=r, column=3).number_format = "@"          # Telefon — har doim MATN, "3,5E+11" bo'lib qolmasin
        ws.cell(row=r, column=5).number_format = "#,##0"      # Narxi — minglik ajratkichli chiroyli raqam
        ws.cell(row=r, column=7).number_format = "DD.MM.YYYY HH:MM"  # Sana

    widths = [6, 22, 16, 34, 14, 16, 18]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = "A2"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"bookinglar_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    buffer.name = filename

    await query.answer()
    await query.message.reply_document(
        document=buffer,
        filename=filename,
        caption=f"📤 Jami {len(rows)} ta booking eksport qilindi."
    )
    return ADMIN_MENU


# ==================== KONTAKTLAR / BIZ HAQIMIZDA ====================

def get_or_create_clinic_info() -> ClinicInfo:
    """Har doim bitta qatordan iborat ClinicInfo'ni qaytaradi, yo'q bo'lsa yaratadi."""
    info = ClinicInfo.query.first()
    if not info:
        info = ClinicInfo()
        db.session.add(info)
        db.session.commit()
    return info


async def show_clinic_info(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Klinika ma'lumotlarini (manzil/telefon/ish vaqti/joylashuv) ko'rsatadi va tahrirlash tugmalarini beradi."""
    with flask_app.app_context():
        info = get_or_create_clinic_info()
        text = (
            "📍 <b>Kontaktlar / Biz haqimizda</b>\n\n"
            f"🏠 Manzil: {info.address or '— (kiritilmagan)'}\n"
            f"📞 Telefon: {info.phone or '— (kiritilmagan)'}\n"
            f"🕒 Ish vaqti: {info.working_hours or '— (kiritilmagan)'}\n"
            f"🗺 Xarita: {'✅ o‘rnatilgan' if info.latitude is not None else '— (kiritilmagan)'}"
        )

    keyboard = [
        [InlineKeyboardButton("✏️ Manzil", callback_data="clinicf_address"),
         InlineKeyboardButton("✏️ Telefon", callback_data="clinicf_phone")],
        [InlineKeyboardButton("✏️ Ish vaqti", callback_data="clinicf_working_hours")],
        [InlineKeyboardButton("📍 Joylashuvni o'rnatish", callback_data="clinicf_location")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def clinic_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manzil/telefon/ish vaqti matn holatida kiritiladi."""
    field = context.user_data.get("clinic_field")
    value = update.message.text.strip()

    with flask_app.app_context():
        info = get_or_create_clinic_info()
        setattr(info, field, value)
        db.session.commit()

    keyboard = [[InlineKeyboardButton("⬅️ Kontaktlarga qaytish", callback_data="adm_contact")]]
    await update.message.reply_text("✅ Yangilandi!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def clinic_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Joylashuvni qabul qiladi — Telegram lokatsiya xabari yoki 'lat,long' matni orqali."""
    keyboard = [[InlineKeyboardButton("⬅️ Kontaktlarga qaytish", callback_data="adm_contact")]]

    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
    else:
        text = (update.message.text or "").strip()
        try:
            lat_str, lon_str = text.split(",")
            lat, lon = float(lat_str.strip()), float(lon_str.strip())
        except (ValueError, AttributeError):
            await update.message.reply_text(
                "Iltimos, Telegram orqali joylashuvni ulashing (📎 tugmasi → Location) "
                "yoki 'kenglik,uzunlik' formatida yozing (masalan: 41.311081,69.240562):"
            )
            return CLINIC_LOCATION

    with flask_app.app_context():
        info = get_or_create_clinic_info()
        info.latitude = lat
        info.longitude = lon
        db.session.commit()

    await update.message.reply_text("✅ Joylashuv saqlandi!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


# ==================== OMMAVIY XABAR (BROADCAST) ====================
# Bosqichlar: 1) Sarlavha  2) Asosiy matn  3) Rasm (IXTIYORIY)  4) Ko'rib chiqish va tasdiqlash
# Rasm bot.py orqali qayta yuklanishi kerak (Telegram file_id botlar orasida ishlamaydi),
# shuning uchun rasm shu yerda lokal papkaga saqlanadi va bazaga faqat fayl yo'li yoziladi.

def get_broadcast_audience_count() -> int:
    with flask_app.app_context():
        return User.query.filter(User.full_name.isnot(None), User.phone.isnot(None)).count()


async def start_broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Broadcast bosqichini boshlaydi — avval sarlavha so'raladi."""
    audience = get_broadcast_audience_count()

    if audience == 0:
        await query.answer("Hozircha ro'yxatdan o'tgan mijozlar yo'q.", show_alert=True)
        return ADMIN_MENU

    context.user_data.pop("broadcast_headline", None)
    context.user_data.pop("broadcast_text", None)
    context.user_data.pop("broadcast_image_path", None)

    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_back")]]
    await query.edit_message_text(
        f"📢 Ommaviy xabar yuborish (1/3)\n\n"
        f"👥 Qabul qiluvchilar: {audience} ta ro'yxatdan o'tgan mijoz\n\n"
        f"Avval xabar SARLAVHASINI (headline) yozing:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_HEADLINE


async def broadcast_headline_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sarlavha qabul qilinadi — endi asosiy matn so'raladi."""
    context.user_data["broadcast_headline"] = update.message.text.strip()

    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_back")]]
    await update.message.reply_text(
        "📢 Ommaviy xabar yuborish (2/3)\n\nEndi xabarning ASOSIY MATNINI yozing:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_TEXT


async def broadcast_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asosiy matn qabul qilinadi — endi rasm (IXTIYORIY) so'raladi."""
    context.user_data["broadcast_text"] = update.message.text.strip()

    keyboard = [
        [InlineKeyboardButton("⏭ Rasmsiz davom etish", callback_data="bc_skip_image")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_back")],
    ]
    await update.message.reply_text(
        "📢 Ommaviy xabar yuborish (3/3)\n\n"
        "Xabarga rasm biriktirmoqchi bo'lsangiz — shu yerga rasm yuboring.\n"
        "Rasmsiz yubormoqchi bo'lsangiz — pastdagi tugmani bosing (BU IXTIYORIY):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_IMAGE


async def broadcast_image_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Rasm qabul qilinadi, lokal papkaga saqlanadi (bot.py qayta yuklab yuborishi uchun)."""
    photo = update.message.photo[-1]  # eng yuqori sifatlisi
    tg_file = await context.bot.get_file(photo.file_id)

    filename = f"broadcast_{uuid.uuid4().hex}.jpg"
    path = os.path.join(BROADCAST_IMAGES_DIR, filename)
    await tg_file.download_to_drive(path)

    context.user_data["broadcast_image_path"] = path
    return await show_broadcast_preview(update.message, context)


async def skip_broadcast_image(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["broadcast_image_path"] = None
    return await show_broadcast_preview(query.message, context)


async def show_broadcast_preview(message_target, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Yakuniy ko'rib chiqish — tasdiqlash yoki bekor qilish."""
    import html as _html

    headline = _html.escape(context.user_data.get("broadcast_headline", ""))
    text = _html.escape(context.user_data.get("broadcast_text", ""))
    image_path = context.user_data.get("broadcast_image_path")
    audience = get_broadcast_audience_count()

    preview = f"📢 <b>{headline}</b>\n\n{text}"
    caption = (
        f"👁 <b>Ko'rib chiqish:</b>\n\n{preview}\n\n"
        f"{'🖼 (rasm biriktirilgan)' if image_path else '(rasmsiz)'}\n\n"
        f"— {audience} ta mijozga yuborishni tasdiqlaysizmi? —"
    )
    keyboard = [
        [InlineKeyboardButton(f"✅ Ha, {audience} ta mijozga yuborish", callback_data="bc_confirm")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="bc_cancel")],
    ]

    if image_path:
        with open(image_path, "rb") as f:
            await message_target.reply_photo(photo=f, caption=caption, parse_mode="HTML",
                                               reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message_target.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def confirm_broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Broadcastni bazaga 'pending' sifatida yozadi — mijozlar botiga ~10 soniya ichida navbat bilan yuboriladi."""
    headline = context.user_data.pop("broadcast_headline", None)
    text = context.user_data.pop("broadcast_text", None)
    image_path = context.user_data.pop("broadcast_image_path", None)

    if not text:
        await query.answer("Xabar topilmadi, qaytadan urinib ko'ring.", show_alert=True)
        return await start_broadcast(query, context)

    with flask_app.app_context():
        bm = BroadcastMessage(headline=headline, text=text, image_path=image_path, status="pending")
        db.session.add(bm)
        db.session.commit()

    await query.message.reply_text(
        "✅ Xabar navbatga qo'yildi!\n\n"
        "Mijozlar botiga (bot.py) yuborilishi bir necha soniya ichida boshlanadi — "
        "u fonda avtomatik ishlaydi.",
        reply_markup=admin_main_keyboard()
    )
    return ADMIN_MENU


async def cancel_broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("broadcast_headline", None)
    context.user_data.pop("broadcast_text", None)
    context.user_data.pop("broadcast_image_path", None)
    await query.message.reply_text("Bekor qilindi.", reply_markup=admin_main_keyboard())
    return ADMIN_MENU


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ADMIN_MENU holatidagi barcha inline tugmalarni boshqaradi."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("faq_noop_") or data == "noop":
        return ADMIN_MENU

    if data == "adm_exit":
        await query.edit_message_text("Admin panel yopildi. Qayta kirish uchun /start bosing.")
        return ConversationHandler.END

    if data == "adm_back":
        await query.edit_message_text("🔧 Jarrohlik Markazi — Admin Panel", reply_markup=admin_main_keyboard())
        return ADMIN_MENU

    if data == "adm_stats":
        with flask_app.app_context():
            total_users = User.query.count()
            referred_total = User.query.filter(User.referred_by_id.isnot(None)).count()

            total_bookings = Booking.query.count()
            week_ago = datetime.utcnow() - timedelta(days=7)
            week_bookings = Booking.query.filter(Booking.created_at >= week_ago).count()

            pending_c = Booking.query.filter_by(status=BookingStatus.PENDING).count()
            confirmed_c = Booking.query.filter_by(status=BookingStatus.CONFIRMED).count()
            cancelled_c = Booking.query.filter_by(status=BookingStatus.CANCELLED).count()
            completed_c = Booking.query.filter_by(status=BookingStatus.COMPLETED).count()

            # Taxminiy daromad — tasdiqlangan va bajarilgan bookinglar narxlari yig'indisi
            revenue_bookings = Booking.query.filter(
                Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED])
            ).all()
            revenue = sum((b.service.price if b.service else 0) for b in revenue_bookings)

            # O'rtacha mijoz bahosi (sharh so'rovi orqali yig'ilgan)
            rated = Booking.query.filter(Booking.rating.isnot(None)).all()
            avg_rating = (sum(b.rating for b in rated) / len(rated)) if rated else None

            # Eng faol taklif qiluvchi (referral tizimi orqali eng ko'p do'st jalb qilgan mijoz)
            referred_users = User.query.filter(User.referred_by_id.isnot(None)).all()
            top_referrer_line = ""
            if referred_users:
                counts = Counter(u.referred_by_id for u in referred_users)
                top_id, top_count = counts.most_common(1)[0]
                top_user = User.query.get(top_id)
                top_name = html.escape(top_user.full_name or top_user.first_name or "?") if top_user else "?"
                top_referrer_line = f"\n🏆 Eng faol taklif qiluvchi: <b>{top_name}</b> ({top_count} ta do'st)"

            services_count = Service.query.count()
            faq_count = FAQ.query.count()

        rating_line = (
            f"⭐ O'rtacha baho: <b>{avg_rating:.1f}/5</b> ({len(rated)} ta sharh)"
            if avg_rating is not None else "⭐ Hali sharhlar yo'q"
        )

        text = (
            "📊 <b>Statistik Dashboard</b>\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
            f"👥 Foydalanuvchilar: <b>{total_users}</b>\n"
            f"🎁 Referral orqali kelganlar: <b>{referred_total}</b>"
            f"{top_referrer_line}\n\n"
            f"📅 Jami bookinglar: <b>{total_bookings}</b>\n"
            f"🆕 So'nggi 7 kunda: <b>{week_bookings}</b>\n\n"
            f"🟡 Kutilayotgan: {pending_c}\n"
            f"🟢 Tasdiqlangan: {confirmed_c}\n"
            f"🔴 Bekor qilingan: {cancelled_c}\n"
            f"✅ Bajarilgan: {completed_c}\n\n"
            f"💰 Taxminiy daromad: <b>{revenue:,.0f} so'm</b>\n"
            f"{rating_line}\n\n"
            f"🏥 Xizmatlar: {services_count}\n"
            f"❓ FAQ: {faq_count}"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU

    if data == "adm_bookings":
        return await show_bookings_filter_menu(query, context)

    if data.startswith("bkf_"):
        filter_key = data[len("bkf_"):]
        context.user_data["bk_filter"] = filter_key
        return await show_bookings_list(query, context, filter_key)

    if data.startswith("bk_view_"):
        booking_id = int(data.rsplit("_", 1)[1])
        return await show_booking_detail(query, context, booking_id)

    if data == "bk_backlist":
        filter_key = context.user_data.get("bk_filter", "all")
        return await show_bookings_list(query, context, filter_key)

    if data.startswith("bk_status_"):
        rest = data[len("bk_status_"):]
        status_str, booking_id_str = rest.rsplit("_", 1)
        return await change_booking_status(query, context, status_str, int(booking_id_str))

    if data.startswith("bk_setdate_"):
        booking_id = int(data.rsplit("_", 1)[1])
        return await ask_appointment_date(query, context, booking_id)

    if data.startswith("bk_delconfirm_"):
        booking_id = int(data.rsplit("_", 1)[1])
        return await delete_booking(query, context, booking_id)

    if data.startswith("bk_delete_"):
        booking_id = int(data.rsplit("_", 1)[1])
        return await confirm_booking_delete(query, context, booking_id)

    if data.startswith("bk_bulkdelconfirm_"):
        filter_key = data[len("bk_bulkdelconfirm_"):]
        return await bulk_delete_bookings(query, context, filter_key)

    if data.startswith("bk_bulkdel_"):
        filter_key = data[len("bk_bulkdel_"):]
        return await confirm_bulk_delete(query, context, filter_key)

    if data == "adm_export":
        return await export_bookings_csv(query, context)

    if data == "adm_contact":
        return await show_clinic_info(query, context)

    if data.startswith("clinicf_"):
        field = data[len("clinicf_"):]
        if field == "location":
            keyboard = [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="adm_contact")]]
            await query.edit_message_text(
                "📍 Joylashuvni yuboring — pastdagi 📎 (biriktirish) tugmasidan Location tanlang, "
                "yoki shu yerga 'kenglik,uzunlik' formatida yozing (masalan: 41.311081,69.240562):",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CLINIC_LOCATION
        context.user_data["clinic_field"] = field
        await query.edit_message_text(f"Yangi qiymatni kiriting ({CLINIC_FIELDS.get(field, field)}):")
        return CLINIC_EDIT_VALUE

    if data == "adm_broadcast":
        return await start_broadcast(query, context)

    if data == "bc_skip_image":
        return await skip_broadcast_image(query, context)

    if data == "bc_confirm":
        return await confirm_broadcast(query, context)

    if data == "bc_cancel":
        return await cancel_broadcast(query, context)

    if data == "adm_services":
        return await show_admin_services(query, context)

    if data == "adm_faq":
        return await show_admin_faq(query, context)

    if data == "asvc_add":
        await query.edit_message_text("Yangi xizmat nomini kiriting:")
        return SVC_NAME

    if data.startswith("asvc_edit_"):
        service_id = int(data.rsplit("_", 1)[1])
        context.user_data["admin_svc_id"] = service_id
        keyboard = [
            [InlineKeyboardButton("📝 Nomi", callback_data="svcf_name"),
             InlineKeyboardButton("📄 Tavsif", callback_data="svcf_description")],
            [InlineKeyboardButton("💰 Narxi", callback_data="svcf_price")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_services")],
        ]
        await query.edit_message_text("Qaysi maydonni tahrirlaysiz?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU

    if data.startswith("svcf_"):
        field = data[len("svcf_"):]
        context.user_data["admin_svc_field"] = field
        await query.edit_message_text(f"Yangi qiymatni kiriting ({SVC_FIELDS.get(field, field)}):")
        return SVC_EDIT_VALUE

    if data.startswith("asvc_delconfirm_"):
        service_id = int(data.rsplit("_", 1)[1])
        with flask_app.app_context():
            service = Service.query.get(service_id)
            if service:
                db.session.delete(service)
                db.session.commit()
        await query.answer("O'chirildi ✅", show_alert=True)
        return await show_admin_services(query, context)

    if data.startswith("asvc_delete_"):
        service_id = int(data.rsplit("_", 1)[1])
        with flask_app.app_context():
            service = Service.query.get(service_id)
            name = service.name if service else "?"
        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"asvc_delconfirm_{service_id}")],
            [InlineKeyboardButton("❌ Yo'q", callback_data="adm_services")],
        ]
        await query.edit_message_text(f"«{name}» xizmatini o'chirishni tasdiqlaysizmi?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU

    if data == "faq_add":
        await query.edit_message_text("Yangi savolni kiriting:")
        return FAQ_Q

    if data.startswith("faq_delete_confirm_"):
        faq_id = int(data.rsplit("_", 1)[1])
        with flask_app.app_context():
            faq = FAQ.query.get(faq_id)
            if faq:
                db.session.delete(faq)
                db.session.commit()
        await query.answer("O'chirildi ✅", show_alert=True)
        return await show_admin_faq(query, context)

    if data.startswith("faq_delete_"):
        faq_id = int(data.rsplit("_", 1)[1])
        with flask_app.app_context():
            faq = FAQ.query.get(faq_id)
            question = faq.question if faq else "?"
        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"faq_delete_confirm_{faq_id}")],
            [InlineKeyboardButton("❌ Yo'q", callback_data="adm_faq")],
        ]
        await query.edit_message_text(f"«{question}» savolini o'chirishni tasdiqlaysizmi?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU

    return ADMIN_MENU


# ---- Yangi xizmat qo'shish (ketma-ket matn holatlari) ----

async def svc_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_svc_name"] = update.message.text.strip()
    await update.message.reply_text("Tavsifini kiriting:")
    return SVC_DESC


async def svc_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_svc_desc"] = update.message.text.strip()
    await update.message.reply_text("Davomiyligini daqiqada kiriting (masalan: 60):")
    return SVC_DURATION


async def svc_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Iltimos, faqat raqam kiriting (masalan: 60):")
        return SVC_DURATION
    context.user_data["new_svc_duration"] = int(text)
    await update.message.reply_text("Narxini so'mda kiriting (masalan: 150000):")
    return SVC_PRICE


async def svc_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleaned = update.message.text.strip().replace(" ", "").replace(",", "")
    if not cleaned.isdigit():
        await update.message.reply_text("Iltimos, faqat raqam kiriting (masalan: 150000):")
        return SVC_PRICE

    with flask_app.app_context():
        service = Service(
            name=context.user_data.pop("new_svc_name"),
            description=context.user_data.pop("new_svc_desc"),
            duration_minutes=context.user_data.pop("new_svc_duration"),
            price=float(cleaned),
        )
        db.session.add(service)
        db.session.commit()

    keyboard = [[InlineKeyboardButton("⬅️ Xizmatlarga qaytish", callback_data="adm_services")]]
    await update.message.reply_text("✅ Yangi xizmat qo'shildi!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def svc_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data.get("admin_svc_field")
    service_id = context.user_data.get("admin_svc_id")
    value = update.message.text.strip()

    with flask_app.app_context():
        service = Service.query.get(service_id)
        if not service:
            await update.message.reply_text("Xizmat topilmadi.")
            return ADMIN_MENU

        if field == "duration_minutes":
            if not value.isdigit():
                await update.message.reply_text("Iltimos, faqat raqam kiriting:")
                return SVC_EDIT_VALUE
            service.duration_minutes = int(value)
        elif field == "price":
            cleaned = value.replace(" ", "").replace(",", "")
            if not cleaned.replace(".", "", 1).isdigit():
                await update.message.reply_text("Iltimos, faqat raqam kiriting:")
                return SVC_EDIT_VALUE
            service.price = float(cleaned)
        elif field == "name":
            service.name = value
        elif field == "description":
            service.description = value

        db.session.commit()

    keyboard = [[InlineKeyboardButton("⬅️ Xizmatlarga qaytish", callback_data="adm_services")]]
    await update.message.reply_text("✅ Yangilandi!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


# ---- Yangi FAQ qo'shish (ketma-ket matn holatlari) ----

async def faq_q(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_faq_q"] = update.message.text.strip()
    await update.message.reply_text("Endi javobni kiriting:")
    return FAQ_A


async def faq_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_faq_a"] = update.message.text.strip()
    await update.message.reply_text("Kategoriyasini kiriting (masalan: Narxi, Qabul vaqtlari):")
    return FAQ_CAT


async def faq_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip()
    with flask_app.app_context():
        faq = FAQ(
            question=context.user_data.pop("new_faq_q"),
            answer=context.user_data.pop("new_faq_a"),
            category=category,
            created_by="admin",
        )
        db.session.add(faq)
        db.session.commit()

    keyboard = [[InlineKeyboardButton("⬅️ FAQ ro'yxatiga qaytish", callback_data="adm_faq")]]
    await update.message.reply_text("✅ Yangi FAQ qo'shildi!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Admin panel yopildi.")
    return ConversationHandler.END


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    if not is_admin(tg_user.id):
        await update.message.reply_text(f"⛔ Sizda admin huquqi yo'q. ID: {tg_user.id}")
        return
    await update.message.reply_text(
        "🔧 Admin Bot\n\n"
        "/start - Admin panelni ochish\n"
        "/cancel - Joriy amalni bekor qilish\n"
        "/help - Bu xabar"
    )


# ==================== ASOSIY DASTUR ====================

async def run_bot():
    application = Application.builder().token(ADMIN_BOT_TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("start", admin_start)],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_router)],
            SVC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_name)],
            SVC_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_desc)],
            SVC_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_duration)],
            SVC_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_price)],
            SVC_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_edit_value)],
            FAQ_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, faq_q)],
            FAQ_A: [MessageHandler(filters.TEXT & ~filters.COMMAND, faq_a)],
            FAQ_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, faq_cat)],
            CLINIC_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic_edit_value)],
            CLINIC_LOCATION: [
                MessageHandler((filters.TEXT | filters.LOCATION) & ~filters.COMMAND, clinic_location),
                CallbackQueryHandler(admin_router),  # "Bekor qilish" tugmasi shu yerdan ham bosilishi mumkin
            ],
            APPOINTMENT_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, appointment_date_received),
                CallbackQueryHandler(admin_router),  # "Bekor qilish" tugmasi shu yerdan ham bosilishi mumkin
            ],
            BROADCAST_HEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_headline_received),
                CallbackQueryHandler(admin_router),
            ],
            BROADCAST_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text_received),
                CallbackQueryHandler(admin_router),
            ],
            BROADCAST_IMAGE: [
                MessageHandler(filters.PHOTO, broadcast_image_received),
                CallbackQueryHandler(admin_router),  # "Rasmsiz davom etish" / "Bekor qilish" shu yerdan
            ],
        },
        fallbacks=[CommandHandler("start", admin_start), CommandHandler("cancel", admin_cancel)],
        allow_reentry=True,
    )

    application.add_handler(admin_conv)
    application.add_handler(CommandHandler("help", admin_help))

    logger.info("Admin bot handlerlari ro'yxatdan o'tkazildi")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Admin bot ishga tushdi — polling boshlandi")

    try:
        await asyncio.Event().wait()  # Ctrl+C bosilguncha ishlaydi
    finally:
        logger.info("Admin bot to'xtatilmoqda...")
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        await application.shutdown()


def main():
    if not ADMIN_BOT_TOKEN:
        raise SystemExit(
            "XATO: ADMIN_BOT_TOKEN .env faylida topilmadi. "
            "@BotFather orqali yangi bot yarating va tokenni .env ga qo'shing."
        )
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
