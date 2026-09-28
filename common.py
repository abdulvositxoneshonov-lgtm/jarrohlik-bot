"""
bot.py va admin_bot.py uchun UMUMIY yordamchi kod.

Ilgari admin guruhidagi kartochka matni/tugmalari ikkala faylda so'zma-so'z takrorlanardi —
biri o'zgarsa, ikkinchisi eskirib qolardi. Endi ikkala bot ham shu yerdagi bitta funksiyani ishlatadi.
"""

import html
import os
import re
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.engine import Engine
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import db, User, Booking, BookingStatus

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


# ==================== VAQT ZONASI ====================
# Operator qabul sanasini MAHALLIY vaqtda kiritadi (masalan "25.12.2026 14:30" — Toshkent vaqti).
# Eslatmalar workeri ham xuddi shu mahalliy vaqt bilan solishtirishi kerak — aks holda UTC bilan
# solishtirilganda (Toshkent = UTC+5) "1 soat qoldi" eslatmasi qabul o'tib ketgandan keyin kelardi.
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Tashkent")
try:
    LOCAL_TZ = ZoneInfo(TIMEZONE_NAME) if ZoneInfo else None
except Exception:
    LOCAL_TZ = None


def local_now() -> datetime:
    """Mahalliy (klinika) vaqtini tzinfo'siz qaytaradi — bazadagi appointment_at bilan solishtirish uchun."""
    if LOCAL_TZ is None:
        return datetime.now()
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


# ==================== BAZA SOZLAMALARI ====================

def configure_db(flask_app, database_url: str) -> None:
    """Flask ilovasini bazaga ulaydi. Ikki bot bitta SQLite faylga bir vaqtda yozgani uchun
    WAL rejimi va busy_timeout yoqiladi — aks holda 'database is locked' xatolari chiqadi."""
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    db.init_app(flask_app)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ==================== TELEFON RAQAM ====================

_PHONE_RE = re.compile(r"^\+?\d{9,15}$")


def normalize_phone(raw: str):
    """Telefon raqamni tozalaydi va tekshiradi. Noto'g'ri bo'lsa None qaytaradi.
    '90 123 45 67' -> '+998901234567', '+998 (90) 123-45-67' -> '+998901234567'."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-()]", "", raw.strip())
    if not _PHONE_RE.match(cleaned):
        return None
    digits = cleaned.lstrip("+")
    if len(digits) == 9:  # O'zbekiston raqami kod'siz kiritilgan
        digits = "998" + digits
    return "+" + digits


# ==================== ADMIN GURUHI KARTOCHKASI ====================

STATUS_EMOJI = {"pending": "🟡", "confirmed": "🟢", "cancelled": "🔴", "completed": "✅"}
STATUS_LABEL = {"pending": "Kutilmoqda", "confirmed": "Tasdiqlangan", "cancelled": "Bekor qilingan", "completed": "Bajarilgan"}


def build_admin_card_text(b: Booking) -> str:
    """Admin GURUHIGA yuboriladigan bildirishnoma kartochkasi matni. Booking holati QAYERDA
    o'zgarishidan qat'iy nazar (guruhda yoki admin botda) shu funksiya chaqiriladi — karta HAR DOIM
    haqiqiy holatni ko'rsatadi. FAQAT flask_app.app_context() ICHIDA chaqirilishi kerak."""
    esc = html.escape
    username_line = f"@{esc(b.user.username)}" if b.user.username else "username yo'q"
    referral_line = ""
    if b.user.referred_by_id:
        referrer = db.session.get(User, b.user.referred_by_id)
        if referrer:
            referrer_label = esc(str(referrer.full_name or referrer.first_name or referrer.telegram_id))
            referral_line = f"🎁 Taklif orqali: {referrer_label}\n"
    display_name = esc(b.user.full_name or b.user.first_name or "Foydalanuvchi")
    status = b.status.value
    text = (
        f"{STATUS_EMOJI.get(status, '⚪')} <b>Qabul Talabi — {STATUS_LABEL.get(status, status)}</b>\n\n"
        f"👤 Ism: {display_name}\n"
        f"📱 Telefon: {esc(b.user.phone or '—')}\n"
        f"💬 Telegram: {username_line}\n"
        f"🔗 Profil: <a href=\"tg://user?id={b.user.telegram_id}\">{display_name}</a>\n"
        f"{referral_line}"
        f"🏥 Xizmat: {esc(b.service.name if b.service else '?')}\n"
    )
    if b.service:
        text += f"💰 Narxi: {b.service.price:,.0f} so'm\n"
    if b.appointment_at:
        text += f"🗓 Qabul vaqti: <b>{b.appointment_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
    if b.rating:
        text += f"⭐ Mijoz bahosi: {'⭐' * b.rating}\n"
    text += f"\nID: {b.id}\nYaratilgan: {b.created_at.strftime('%Y-%m-%d %H:%M')}"
    return text


def build_admin_card_keyboard(b: Booking):
    """Booking holatiga qarab guruhdagi kartochka tugmalari — o'chirish tugmasi ataylab YO'Q
    (o'chirish faqat admin botda, tasdiqlash bilan)."""
    rows = []
    top_row = []
    if b.status != BookingStatus.CONFIRMED:
        top_row.append(InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_{b.id}"))
    if b.status != BookingStatus.CANCELLED:
        top_row.append(InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_{b.id}"))
    if top_row:
        rows.append(top_row)
    bottom_row = []
    if b.status != BookingStatus.COMPLETED:
        bottom_row.append(InlineKeyboardButton("✔️ Bajarildi", callback_data=f"groupdone_{b.id}"))
    if b.status == BookingStatus.CONFIRMED:
        bottom_row.append(InlineKeyboardButton("📅 Sana belgilash", callback_data=f"groupsetdate_{b.id}"))
    if bottom_row:
        rows.append(bottom_row)
    return InlineKeyboardMarkup(rows) if rows else None


# ==================== MIJOZGA HOLAT BILDIRISHNOMALARI ====================
# Booking holati guruhda YOKI admin botda o'zgarganda mijozga uning o'z tilida xabar boradi.

CUSTOMER_STATUS_TEXTS = {
    "confirmed": {
        "lt": "✅ <b>Qabulingiz tasdiqlandi!</b>\n🏥 Xizmat: <b>{service}</b>\n\nOperator tez orada siz bilan bog'lanadi. 🙏",
        "kr": "✅ <b>Қабулингиз тасдиқланди!</b>\n🏥 Хизмат: <b>{service}</b>\n\nОператор тез орада сиз билан боғланади. 🙏",
    },
    "cancelled": {
        "lt": "❌ Afsuski, «<b>{service}</b>» bo'yicha qabulingiz rad etildi. Operator siz bilan bog'lanadi.",
        "kr": "❌ Афсуски, «<b>{service}</b>» бўйича қабулингиз рад этилди. Оператор сиз билан боғланади.",
    },
    "appointment": {
        "lt": "🗓 <b>Qabul vaqti belgilandi!</b>\n🏥 Xizmat: <b>{service}</b>\n📅 Sana: <b>{date}</b>\n\nQabuldan 24 soat va 1 soat oldin eslatma yuboramiz. 🙏",
        "kr": "🗓 <b>Қабул вақти белгиланди!</b>\n🏥 Хизмат: <b>{service}</b>\n📅 Сана: <b>{date}</b>\n\nҚабулдан 24 соат ва 1 соат олдин эслатма юборамиз. 🙏",
    },
}


def customer_status_text(kind: str, lang: str, **kwargs) -> str:
    texts = CUSTOMER_STATUS_TEXTS[kind]
    return texts.get(lang, texts["kr"]).format(**kwargs)
