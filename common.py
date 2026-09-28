"""
bot.py va admin_bot.py uchun UMUMIY yordamchi kod.

Ilgari admin guruhidagi kartochka matni/tugmalari ikkala faylda so'zma-so'z takrorlanardi —
biri o'zgarsa, ikkinchisi eskirib qolardi. Endi ikkala bot ham shu yerdagi bitta funksiyani ishlatadi.
"""

import asyncio
import html
import logging
import os
import re
from datetime import datetime, date, time, timedelta

from sqlalchemy import event
from sqlalchemy.engine import Engine
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import db, User, Service, Booking, BookingStatus, AppState

logger = logging.getLogger(__name__)

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


# ==================== ISH JADVALI (MIJOZ O'ZI VAQT TANLASHI UCHUN) ====================

def _parse_hm(value: str, fallback: str) -> time:
    try:
        return datetime.strptime((value or fallback).strip(), "%H:%M").time()
    except ValueError:
        return datetime.strptime(fallback, "%H:%M").time()


# ISO hafta kunlari: 1=Dushanba ... 7=Yakshanba (standart: Du–Sha)
WORK_DAYS = {int(x) for x in os.getenv("WORK_DAYS", "1,2,3,4,5,6").split(",") if x.strip().isdigit()}
WORK_START = _parse_hm(os.getenv("WORK_START"), "09:00")
WORK_END = _parse_hm(os.getenv("WORK_END"), "18:00")
SLOT_MINUTES = max(10, int(os.getenv("SLOT_MINUTES", "60") or 60))
BOOKING_DAYS_AHEAD = max(1, int(os.getenv("BOOKING_DAYS_AHEAD", "7") or 7))
MIN_LEAD_MINUTES = int(os.getenv("MIN_LEAD_MINUTES", "60") or 60)  # hozirdan kamida shuncha keyin
SLOT_CAPACITY = max(1, int(os.getenv("SLOT_CAPACITY", "1") or 1))   # bitta xizmat uchun bir vaqtda nechta mijoz

WEEKDAY_SHORT = {
    "lt": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
    "kr": ["Ду", "Се", "Чо", "Па", "Жу", "Ша", "Як"],
}


def day_slots(d: date):
    """Berilgan kunning barcha ish vaqti slotlari (bandligidan qat'i nazar)."""
    if d.isoweekday() not in WORK_DAYS:
        return []
    slots = []
    current = datetime.combine(d, WORK_START)
    end = datetime.combine(d, WORK_END)
    while current + timedelta(minutes=SLOT_MINUTES) <= end:
        slots.append(current)
        current += timedelta(minutes=SLOT_MINUTES)
    return slots


def busy_slot_counts(service_id: int, start: datetime, end: datetime) -> dict:
    """[start, end) oralig'ida shu xizmat uchun band slotlar -> nechta bron. app_context ichida chaqiriladi."""
    rows = db.session.query(Booking.appointment_at, db.func.count(Booking.id)).filter(
        Booking.service_id == service_id,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        Booking.appointment_at >= start,
        Booking.appointment_at < end,
    ).group_by(Booking.appointment_at).all()
    return dict(rows)


def free_slots(service_id: int, d: date):
    """Shu kun uchun bo'sh (va hali o'tib ketmagan) slotlar. app_context ichida chaqiriladi."""
    earliest = local_now() + timedelta(minutes=MIN_LEAD_MINUTES)
    slots = [s for s in day_slots(d) if s >= earliest]
    if not slots:
        return []
    busy = busy_slot_counts(service_id, datetime.combine(d, time.min), datetime.combine(d + timedelta(days=1), time.min))
    return [s for s in slots if busy.get(s, 0) < SLOT_CAPACITY]


def available_dates(service_id: int):
    """Yaqin BOOKING_DAYS_AHEAD kun ichida kamida bitta bo'sh sloti bor kunlar. app_context ichida."""
    today = local_now().date()
    return [
        today + timedelta(days=i) for i in range(BOOKING_DAYS_AHEAD + 1)
        if free_slots(service_id, today + timedelta(days=i))
    ]


def is_slot_free(service_id: int, slot: datetime) -> bool:
    return slot in free_slots(service_id, slot.date())


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
        "lt": "✅ <b>Qabulingiz tasdiqlandi!</b>\n🏥 Xizmat: <b>{service}</b>{date_line}\n\nOperator tez orada siz bilan bog'lanadi. 🙏",
        "kr": "✅ <b>Қабулингиз тасдиқланди!</b>\n🏥 Хизмат: <b>{service}</b>{date_line}\n\nОператор тез орада сиз билан боғланади. 🙏",
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
    if kind == "confirmed":
        appt = kwargs.pop("appointment_at", None)
        label = "Сана" if lang == "kr" else "Sana"
        kwargs["date_line"] = f"\n📅 {label}: <b>{appt.strftime('%d.%m.%Y %H:%M')}</b>" if appt else ""
    return texts.get(lang, texts["kr"]).format(**kwargs)


# ==================== OMMAVIY XABAR AUDITORIYASI ====================
# Kalitlar BroadcastMessage.audience ustunida saqlanadi. "service:<id>" — shu xizmatga yozilganlar.

AUDIENCE_LABELS = {
    "all": "👥 Barcha mijozlar",
    "active30": "🔥 So'nggi 30 kunda bron qilganlar",
    "completed": "✅ Qabulda bo'lganlar (bajarilgan bron)",
    "nobooking": "🆕 Hali bron qilmaganlar",
    "lang:lt": "🔤 Lotin tilidagilar",
    "lang:kr": "🔤 Kirill tilidagilar",
}


def audience_label(audience: str) -> str:
    audience = audience or "all"
    if audience.startswith("service:"):
        try:
            svc = db.session.get(Service, int(audience.split(":", 1)[1]))
        except ValueError:
            svc = None
        return f"{svc.name if svc else '?'} xizmatiga yozilganlar"
    return AUDIENCE_LABELS.get(audience, AUDIENCE_LABELS["all"])


def audience_query(audience: str):
    """Tanlangan auditoriyadagi ro'yxatdan o'tgan mijozlarning telegram_id so'rovi. app_context ichida."""
    audience = audience or "all"
    q = db.session.query(User.telegram_id).filter(User.full_name.isnot(None), User.phone.isnot(None))
    booked_users = db.session.query(Booking.user_id)
    if audience == "active30":
        q = q.filter(User.id.in_(booked_users.filter(Booking.created_at >= datetime.utcnow() - timedelta(days=30))))
    elif audience == "completed":
        q = q.filter(User.id.in_(booked_users.filter(Booking.status == BookingStatus.COMPLETED)))
    elif audience == "nobooking":
        q = q.filter(~User.id.in_(booked_users))
    elif audience.startswith("lang:"):
        lang = audience.split(":", 1)[1]
        # Tilini tanlamagan eski mijozlar standart bo'yicha kirill hisoblanadi
        q = q.filter(User.language == lang) if lang == "lt" else q.filter((User.language == lang) | User.language.is_(None))
    elif audience.startswith("service:"):
        try:
            service_id = int(audience.split(":", 1)[1])
        except ValueError:
            service_id = -1
        q = q.filter(User.id.in_(booked_users.filter(Booking.service_id == service_id)))
    return q.distinct()


# ==================== KUNLIK VAZIFALAR (HISOBOT, ZAXIRA NUSXA) ====================

def utc_offset() -> timedelta:
    """Mahalliy vaqt va UTC farqi (created_at UTC'da saqlanadi, kunlar esa mahalliy vaqtda hisoblanadi)."""
    minutes = round((local_now() - datetime.utcnow()).total_seconds() / 60)
    return timedelta(minutes=minutes)


def local_day_bounds_utc(d: date):
    """Mahalliy kun [00:00, 24:00) chegaralari UTC'da — created_at bilan solishtirish uchun."""
    start = datetime.combine(d, time.min) - utc_offset()
    return start, start + timedelta(days=1)


def get_state(key: str):
    row = db.session.get(AppState, key)
    return row.value if row else None


def set_state(key: str, value: str) -> None:
    row = db.session.get(AppState, key)
    if row:
        row.value = value
    else:
        db.session.add(AppState(key=key, value=value))
    db.session.commit()


async def run_daily(flask_app, key: str, at: time, job, window_hours: int = 3):
    """Har kuni mahalliy `at` vaqtida `job()` ni BIR MARTA ishga tushiradi. Oxirgi bajarilgan sana
    bazada saqlanadi — bot qayta ishga tushsa ham takrorlanmaydi. Bot o'sha vaqtda o'chiq bo'lsa,
    `window_hours` ichida yoqilsa ham bajariladi, undan keyin esa ertangi kunga qoldiriladi."""
    while True:
        try:
            now = local_now()
            target = datetime.combine(now.date(), at)
            if target <= now < target + timedelta(hours=window_hours):
                with flask_app.app_context():
                    done_today = get_state(key) == now.date().isoformat()
                if not done_today:
                    await job()
                    with flask_app.app_context():
                        set_state(key, now.date().isoformat())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Kunlik vazifa '{key}' xatosi: {e}")
        await asyncio.sleep(60)


def parse_daily_time(env_name: str, default: str):
    """.env'dagi 'SS:DD' qiymat; bo'sh qoldirilsa vazifa o'chirilgan (None)."""
    raw = os.getenv(env_name, default).strip()
    if not raw:
        return None
    return _parse_hm(raw, default)


def build_daily_report(day: date = None) -> str:
    """Operatorlar uchun kunlik hisobot matni (HTML). app_context ichida chaqiriladi."""
    esc = html.escape
    day = day or local_now().date()
    yesterday = day - timedelta(days=1)

    todays = Booking.query.filter(
        Booking.appointment_at >= datetime.combine(day, time.min),
        Booking.appointment_at < datetime.combine(day + timedelta(days=1), time.min),
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
    ).order_by(Booking.appointment_at).all()

    lines = [
        f"📊 <b>Kunlik hisobot — {WEEKDAY_SHORT['lt'][day.weekday()]} {day:%d.%m.%Y}</b>",
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈",
        f"🗓 <b>Bugungi qabullar: {len(todays)} ta</b>",
    ]
    for b in todays[:40]:
        name = esc(b.user.full_name or b.user.first_name or "?") if b.user else "?"
        phone = esc(b.user.phone or "") if b.user else ""
        svc = esc(b.service.name if b.service else "?")
        lines.append(f"{STATUS_EMOJI.get(b.status.value, '⚪')} {b.appointment_at:%H:%M} — {name} {phone} — {svc}")
    if len(todays) > 40:
        lines.append(f"… va yana {len(todays) - 40} ta")
    if not todays:
        lines.append("— bugun belgilangan qabul yo'q")

    pending_total = Booking.query.filter(Booking.status == BookingStatus.PENDING).count()
    pending_no_date = Booking.query.filter(
        Booking.status == BookingStatus.PENDING, Booking.appointment_at.is_(None)
    ).count()

    y_start, y_end = local_day_bounds_utc(yesterday)
    y_bookings = Booking.query.filter(Booking.created_at >= y_start, Booking.created_at < y_end).count()
    y_users = User.query.filter(User.created_at >= y_start, User.created_at < y_end).count()
    y_appts = Booking.query.filter(
        Booking.appointment_at >= datetime.combine(yesterday, time.min),
        Booking.appointment_at < datetime.combine(day, time.min),
    )
    y_completed = y_appts.filter(Booking.status == BookingStatus.COMPLETED).count()
    y_cancelled = y_appts.filter(Booking.status == BookingStatus.CANCELLED).count()
    y_unmarked = y_appts.filter(Booking.status == BookingStatus.CONFIRMED).count()
    avg_rating, rating_count = db.session.query(db.func.avg(Booking.rating), db.func.count(Booking.rating)).filter(
        Booking.rating.isnot(None)
    ).one()

    lines += [
        "",
        f"🟡 Javob kutayotgan bronlar: <b>{pending_total}</b> (sanasi belgilanmagan: {pending_no_date})",
        "",
        f"📈 <b>Kecha ({yesterday:%d.%m})</b>",
        f"🆕 Yangi bronlar: {y_bookings}",
        f"👥 Yangi foydalanuvchilar: {y_users}",
        f"✅ Bajarilgan qabullar: {y_completed}",
        f"🔴 Bekor qilingan qabullar: {y_cancelled}",
    ]
    if y_unmarked:
        lines.append(f"⚠️ Holati belgilanmagan (Bajarildi bosilmagan): {y_unmarked}")
    if rating_count:
        lines.append(f"⭐ O'rtacha baho: {avg_rating:.1f}/5 ({rating_count} ta sharh)")
    return "\n".join(lines)
