import logging
import os
import re
import asyncio
import difflib
from datetime import datetime
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
)
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-5127216730"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")

# ---- Majburiy guruh a'zoligi (force-subscribe) ----
# REQUIRED_GROUP_ID: guruh/kanalning raqamli ID'si (masalan -1001234567890) yoki "@guruh_username".
# REQUIRED_GROUP_LINK: foydalanuvchiga ko'rsatiladigan qo'shilish havolasi (https://t.me/...).
# Ikkalasi ham to'ldirilmasa, majburiy a'zolik tekshiruvi butunlay o'chirilgan hisoblanadi (eski xatti-harakat saqlanadi).
_raw_group_id = os.getenv("REQUIRED_GROUP_ID", "").strip()
if _raw_group_id.lstrip("-").isdigit():
    REQUIRED_GROUP_ID = int(_raw_group_id)
elif _raw_group_id:
    REQUIRED_GROUP_ID = _raw_group_id  # masalan: "@guruh_username"
else:
    REQUIRED_GROUP_ID = None
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "").strip() or None
SUBSCRIPTION_GATE_ENABLED = bool(REQUIRED_GROUP_ID and REQUIRED_GROUP_LINK)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if not SUBSCRIPTION_GATE_ENABLED:
    logger.warning(
        "REQUIRED_GROUP_ID / REQUIRED_GROUP_LINK sozlanmagan — majburiy guruh a'zoligi tekshiruvi O'CHIRILGAN."
    )

# Conversation holatlari
LANG, NAME, PHONE, SUBSCRIBE, MENU, CONFIRM = range(6)

# broadcast_worker() fonda xabar yuborishi uchun Application obyektiga murojaat qiladi
application_instance = None

SERVICES_DATA = [
    {"name": "🏥 Bariatrik Operatsiya", "description": "Og'irlik kamaytirish operatsiyasi", "duration_minutes": 180, "price": 3500000},
    {"name": "💊 Endokrinologiya", "description": "Endokrin tizimi kasalliklari bo'yicha mutaxassis konsultatsiyasi", "duration_minutes": 60, "price": 150000},
    {"name": "🔬 Proktalogiya", "description": "Rektum va kolon kasalliklari bo'yicha mutaxassis yordami", "duration_minutes": 90, "price": 200000},
    {"name": "👩‍⚕️ Ginekologiya", "description": "Ayol sog'lig'i bo'yicha mutaxassis konsultatsiyasi", "duration_minutes": 60, "price": 180000},
    {"name": "👨‍⚕️ Mutaxassis Konsultatsiyasi", "description": "Umumiy sog'lig'i bo'yicha mutaxassis yordami", "duration_minutes": 45, "price": 120000},
]

flask_app = Flask(__name__)
flask_app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(flask_app)

with flask_app.app_context():
    db.create_all()
    if Service.query.count() == 0:
        for s in SERVICES_DATA:
            db.session.add(Service(
                name=s["name"], description=s["description"],
                duration_minutes=s["duration_minutes"], price=s["price"],
                icon=s["name"].split()[0]
            ))
        db.session.commit()
        logger.info("Xizmatlar tekshirildi/qo'shildi")


# ==================== TIL MATNLARI (LOTIN/KIRILL) ====================

# Xabarlarni bo'limlarga ajratib ko'rsatish uchun vizual chiziq (premium ko'rinish)
SEP = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

TEXTS = {
    "choose_lang": {
        "lt": "🌐 Tilni tanlang / Тилни танланг:",
        "kr": "🌐 Тилни танланг / Tilni tanlang:",
    },
    "ask_name": {
        "lt": "✍️ <b>Ismingizni kiriting:</b>",
        "kr": "✍️ <b>Исмингизни киритинг:</b>",
    },
    "ask_phone": {
        "lt": "Rahmat, <b>{name}</b>! 😊\n\n📱 Endi telefon raqamingizni pastdagi tugma orqali ulashing yoki yozib yuboring:",
        "kr": "Рахмат, <b>{name}</b>! 😊\n\n📱 Энди телефон рақамингизни пастдаги тугма орқали улашинг ёки ёзиб юборинг:",
    },
    "share_contact_btn": {
        "lt": "📱 Kontaktni ulashish",
        "kr": "📱 Контактни улашиш",
    },
    "cancel_btn": {
        "lt": "Bekor qilish",
        "kr": "Бекор қилиш",
    },
    "registered": {
        "lt": "✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n" + SEP + "\n👤 Ism: <b>{name}</b>\n📱 Telefon: <b>{phone}</b>",
        "kr": "✅ <b>Рўйхатдан муваффақиятли ўтдингиз!</b>\n" + SEP + "\n👤 Исм: <b>{name}</b>\n📱 Телефон: <b>{phone}</b>",
    },
    "choose_service": {
        "lt": "🏥 <b>Jarrohlik Markazi</b> sizga quyidagi xizmatlarni taklif qiladi.\n\nQaysi xizmatga yozilmoqchisiz? 👇",
        "kr": "🏥 <b>Жарроҳлик Маркази</b> сизга қуйидаги хизматларни таклиф қилади.\n\nҚайси хизматга ёзилмоқчисиз? 👇",
    },
    "welcome_back": {
        "lt": "👋 <b>Xush kelibsiz, {name}!</b>\n\n🏥 <b>Jarrohlik Markazi</b> sizga quyidagi xizmatlarni taklif qiladi.\n\nQaysi xizmatga yozilmoqchisiz? 👇",
        "kr": "👋 <b>Хуш келибсиз, {name}!</b>\n\n🏥 <b>Жарроҳлик Маркази</b> сизга қуйидаги хизматларни таклиф қилади.\n\nҚайси хизматга ёзилмоқчисиз? 👇",
    },
    "confirm_text": {
        "lt": "📋 <b>Qabul ma'lumotlari</b>\n" + SEP + "\n👤 Ism: <b>{name}</b>\n📱 Telefon: <b>{phone}</b>\n🏥 Xizmat: <b>{service}</b>\n💰 Narxi: <b>{price} so'm</b>\n" + SEP + "\n📞 Operator tez orada siz bilan bog'lanib, aniq sana va vaqtni belgilaydi.\n\n✅ Barcha ma'lumotlar to'g'rimi?",
        "kr": "📋 <b>Қабул маълумотлари</b>\n" + SEP + "\n👤 Исм: <b>{name}</b>\n📱 Телефон: <b>{phone}</b>\n🏥 Хизмат: <b>{service}</b>\n💰 Нархи: <b>{price} сўм</b>\n" + SEP + "\n📞 Оператор тез орада сиз билан боғланиб, аниқ сана ва вақтни белгилайди.\n\n✅ Барча маълумотлар тўғрими?",
    },
    "confirm_btn": {"lt": "✅ Tasdiqlash", "kr": "✅ Тасдиқлаш"},
    "back_to_services": {"lt": "⬅️ Boshqa xizmat", "kr": "⬅️ Бошқа хизмат"},
    "booking_success": {
        "lt": "✅ <b>Qabulingiz muvaffaqiyatli band qilindi!</b>\n" + SEP + "\n🆔 Qabul ID: <b>{id}</b>\n📞 Operator tez orada siz bilan bog'lanadi. 🙏",
        "kr": "✅ <b>Қабулингиз муваффақиятли банд қилинди!</b>\n" + SEP + "\n🆔 Қабул ID: <b>{id}</b>\n📞 Оператор тез орада сиз билан боғланади. 🙏",
    },
    "another_service": {"lt": "➕ Yana xizmat tanlash", "kr": "➕ Яна хизмат танлаш"},
    "finish_btn": {"lt": "🏁 Tugatish", "kr": "🏁 Тугатиш"},
    "cancelled": {
        "lt": "Bekor qilindi. Qayta boshlash uchun /start bosing.",
        "kr": "Бекор қилинди. Қайта бошлаш учун /start босинг.",
    },
    "finished": {
        "lt": "Rahmat! Yana kerak bo'lsa /start bosing. 🙏",
        "kr": "Рахмат! Яна керак бўлса /start босинг. 🙏",
    },
    "no_services": {
        "lt": "Afsuski, hozircha hech qanday xizmat mavjud emas.",
        "kr": "Афсуски, ҳозирча ҳеч қандай хизмат мавжуд эмас.",
    },
    "subscribe_prompt": {
        "lt": "🔒 <b>Botdan to'liq foydalanish uchun</b> avval bizning rasmiy Telegram guruhimizga a'zo bo'lishingiz kerak:\n\n1️⃣ Pastdagi «➕ Guruhga qo'shilish» tugmasini bosing\n2️⃣ Guruhga a'zo bo'ling\n3️⃣ Shu yerga qaytib «✅ A'zo bo'ldim» tugmasini bosing",
        "kr": "🔒 <b>Ботдан тўлиқ фойдаланиш учун</b> аввал бизнинг расмий Telegram гуруҳимизга аъзо бўлишингиз керак:\n\n1️⃣ Пастдаги «➕ Гуруҳга қўшилиш» тугмасини босинг\n2️⃣ Гуруҳга аъзо бўлинг\n3️⃣ Шу ерга қайтиб «✅ Аъзо бўлдим» тугмасини босинг",
    },
    "join_group_btn": {"lt": "➕ Guruhga qo'shilish", "kr": "➕ Гуруҳга қўшилиш"},
    "check_subscribed_btn": {"lt": "✅ A'zo bo'ldim", "kr": "✅ Аъзо бўлдим"},
    "not_subscribed_alert": {
        "lt": "❌ Siz hali guruhga a'zo bo'lmagansiz.\nIltimos, avval guruhga qo'shiling, so'ng qayta urinib ko'ring.",
        "kr": "❌ Сиз ҳали гуруҳга аъзо бўлмагансиз.\nИлтимос, аввал гуруҳга қўшилинг, сўнг қайта уриниб кўринг.",
    },
    "subscribe_check_error": {
        "lt": "⚠️ Tekshirishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        "kr": "⚠️ Текширишда хатолик юз берди. Бироздан сўнг қайта уриниб кўринг.",
    },
    "subscribed_success": {
        "lt": "✅ Rahmat! A'zoligingiz tasdiqlandi.",
        "kr": "✅ Рахмат! Аъзолигингиз тасдиқланди.",
    },
    "faq_list_title": {
        "lt": "❓ <b>Tez-tez so'raladigan savollar</b>\n\nQiziqtirgan savolni tanlang 👇",
        "kr": "❓ <b>Тез-тез сўраладиган саволлар</b>\n\nҚизиқтирган саволни танланг 👇",
    },
    "faq_back_btn": {"lt": "⬅️ Ro'yxatga qaytish", "kr": "⬅️ Рўйхатга қайтиш"},
    "faq_operator_btn": {"lt": "👨‍⚕️ Operatorga ulanish", "kr": "👨‍⚕️ Операторга уланиш"},
    "faq_not_found": {
        "lt": "Bu savol topilmadi, ehtimol o'chirilgan. /faq buyrug'ini qayta bosing.",
        "kr": "Бу савол топилмади, эҳтимол ўчирилган. /faq буйруғини қайта босинг.",
    },
    "no_faq": {
        "lt": "Hozircha FAQ mavjud emas.",
        "kr": "Ҳозирча FAQ мавжуд эмас.",
    },
    "my_bookings_btn": {"lt": "📋 Mening bronlarim", "kr": "📋 Менинг бронларим"},
    "about_btn": {"lt": "📍 Biz haqimizda", "kr": "📍 Биз ҳақимизда"},
    "my_bookings_title": {
        "lt": "📋 <b>Mening bronlarim</b>",
        "kr": "📋 <b>Менинг бронларим</b>",
    },
    "my_bookings_empty": {
        "lt": "Sizda hali bronlar mavjud emas. Xizmat tanlab, birinchi bronni rasmiylashtiring!",
        "kr": "Сизда ҳали бронлар мавжуд эмас. Хизмат танлаб, биринчи бронни расмийлаштиринг!",
    },
    "my_booking_detail": {
        "lt": "📋 <b>Bron #{id}</b>\n{emoji} {status}\n" + SEP + "\n🏥 Xizmat: <b>{service}</b>\n💰 Narxi: <b>{price} so'm</b>\n📅 Sana: {date}",
        "kr": "📋 <b>Брон #{id}</b>\n{emoji} {status}\n" + SEP + "\n🏥 Хизмат: <b>{service}</b>\n💰 Нархи: <b>{price} сўм</b>\n📅 Сана: {date}",
    },
    "cancel_my_booking_btn": {"lt": "❌ Bronni bekor qilish", "kr": "❌ Бронни бекор қилиш"},
    "back_to_my_bookings_btn": {"lt": "⬅️ Ro'yxatga qaytish", "kr": "⬅️ Рўйхатга қайтиш"},
    "my_booking_cancel_confirm": {
        "lt": "«<b>{service}</b>» bronini rostdan ham bekor qilmoqchimisiz?",
        "kr": "«<b>{service}</b>» бронини ростдан ҳам бекор қилмоқчимисиз?",
    },
    "yes_cancel_btn": {"lt": "✅ Ha, bekor qilish", "kr": "✅ Ҳа, бекор қилиш"},
    "no_keep_btn": {"lt": "❌ Yo'q", "kr": "❌ Йўқ"},
    "my_booking_cancelled": {
        "lt": "✅ Bron bekor qilindi.",
        "kr": "✅ Брон бекор қилинди.",
    },
    "back_to_menu_btn": {"lt": "⬅️ Menyuga qaytish", "kr": "⬅️ Менюга қайтиш"},
    "about_text_filled": {
        "lt": "📍 <b>Biz haqimizda</b>\n" + SEP + "\n🏥 Manzil: {address}\n📞 Telefon: {phone}\n🕒 Ish vaqti: {hours}",
        "kr": "📍 <b>Биз ҳақимизда</b>\n" + SEP + "\n🏥 Манзил: {address}\n📞 Телефон: {phone}\n🕒 Иш вақти: {hours}",
    },
    "about_not_set": {
        "lt": "Hali to'ldirilmagan",
        "kr": "Ҳали тўлдирилмаган",
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    """Berilgan til uchun matnni qaytaradi (default: kirill)."""
    template = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get("kr", "")
    return template.format(**kwargs) if kwargs else template


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "kr")


def esc(value) -> str:
    """HTML formatlashda buzilib qolmasligi uchun foydalanuvchi/baza matnini xavfsizlashtiradi."""
    import html as _html
    return _html.escape(str(value)) if value is not None else ""


def user_mention_html(tg_user, label: str = None) -> str:
    """Foydalanuvchi profiliga bosiladigan HTML havola — username bo'lmasa ham ID orqali ochiladi."""
    name = esc(label or tg_user.first_name or "Foydalanuvchi")
    return f'<a href="tg://user?id={tg_user.id}">{name}</a>'


# ==================== FAQ QIDIRUV (LOTIN/KIRILL MOSLASHTIRISH) ====================

CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q",
    "ғ": "g", "ҳ": "h",
}

FAQ_MATCH_THRESHOLD = 0.4


def normalize_text(text: str) -> str:
    """Lotin/kirill matnni umumiy (lotin, kichik harf, faqat harf-raqam) shaklga keltiradi — moslashtirish uchun."""
    text = text.lower()
    text = "".join(CYR_TO_LAT.get(ch, ch) for ch in text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_best_faq(question: str, faqs: list):
    """FAQ ro'yxatidan savolga eng mos keladiganini topadi. (faq, score) qaytaradi."""
    norm_q = normalize_text(question)
    if not norm_q:
        return None, 0.0
    q_words = set(norm_q.split())

    best_faq = None
    best_score = 0.0
    for faq in faqs:
        norm_faq_q = normalize_text(faq.question)
        faq_words = set(norm_faq_q.split())
        overlap = len(q_words & faq_words) / max(len(q_words), 1)
        ratio = difflib.SequenceMatcher(None, norm_q, norm_faq_q).ratio()
        score = max(overlap, ratio)
        if score > best_score:
            best_score = score
            best_faq = faq
    return best_faq, best_score


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def is_subscribed(bot, user_id: int):
    """
    Foydalanuvchi majburiy guruhga a'zo ekanligini Telegram API orqali XAVFSIZ tekshiradi
    (foydalanuvchining o'z so'ziga emas, real API javobiga ishonamiz).

    Qaytaradi:
        True  — a'zo (creator/administrator/member, yoki cheklangan bo'lsa ham hali a'zo)
        False — a'zo emas (left/kicked) yoki umuman topilmadi
        None  — tekshirib bo'lmadi (API xatosi, masalan bot guruhga qo'shilmagan)
    """
    if not SUBSCRIPTION_GATE_ENABLED:
        return True

    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_GROUP_ID, user_id=user_id)
    except Exception as e:
        logger.error(f"Obuna tekshiruvida xatolik (bot guruhga a'zo emasmi?): {e}")
        return None

    status = member.status
    if status in ("creator", "administrator", "member"):
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False  # left, kicked va hokazo


async def send_subscription_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Majburiy guruhga qo'shilish so'rovini ko'rsatadi."""
    lang = get_lang(context)
    keyboard = [
        [InlineKeyboardButton(t("join_group_btn", lang), url=REQUIRED_GROUP_LINK)],
        [InlineKeyboardButton(t("check_subscribed_btn", lang), callback_data="check_subscription")],
    ]
    text = t("subscribe_prompt", lang)
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return SUBSCRIBE


async def verify_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """«✅ A'zo bo'ldim» tugmasi bosilganda — real API orqali qayta tekshiradi."""
    query = update.callback_query
    lang = get_lang(context)
    tg_user = update.effective_user

    subscribed = await is_subscribed(context.bot, tg_user.id)

    if subscribed is None:
        await query.answer(t("subscribe_check_error", lang), show_alert=True)
        return SUBSCRIBE

    if not subscribed:
        await query.answer(t("not_subscribed_alert", lang), show_alert=True)
        return SUBSCRIBE

    await query.answer()
    await query.edit_message_text(t("subscribed_success", lang))
    greet = context.user_data.pop("greet_after_subscribe", False)
    return await send_service_menu(update, context, greet=greet)


def build_services_keyboard(lang: str, services) -> InlineKeyboardMarkup:
    """Xizmatlar tugmalari + tezkor havolalar + qo'shimcha bo'limlar + bekor qilish tugmasini yasaydi."""
    keyboard = [[InlineKeyboardButton(s.name, callback_data=f"svc_{s.id}")] for s in services]

    with flask_app.app_context():
        links = QuickLink.query.order_by(QuickLink.sort_order, QuickLink.id).all()
        link_rows = [[InlineKeyboardButton(link.title, url=link.url)] for link in links]

    keyboard.extend(link_rows)
    keyboard.append([
        InlineKeyboardButton(t("my_bookings_btn", lang), callback_data="mybookings_list"),
        InlineKeyboardButton(t("about_btn", lang), callback_data="about_clinic"),
    ])
    keyboard.append([InlineKeyboardButton(t("cancel_btn", lang), callback_data="svc_cancel")])
    return InlineKeyboardMarkup(keyboard)


async def send_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, greet: bool = False) -> int:
    """Xizmatlar ro'yxatini ko'rsatadi (yangi xabar sifatida)."""
    lang = get_lang(context)
    if update.effective_chat:
        await cleanup_stray_location(context, update.effective_chat.id)
    with flask_app.app_context():
        services = Service.query.all()

    if not services:
        text = t("no_services", lang)
        if update.callback_query:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    reply_markup = build_services_keyboard(lang, services)

    if greet:
        text = t("welcome_back", lang, name=esc(context.user_data.get("name", "")))
    else:
        text = t("choose_service", lang)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return MENU


async def edit_service_menu(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xizmatlar ro'yxatini mavjud xabarni tahrirlab ko'rsatadi."""
    lang = get_lang(context)
    await cleanup_stray_location(context, query.message.chat_id)
    with flask_app.app_context():
        services = Service.query.all()

    reply_markup = build_services_keyboard(lang, services)
    await query.edit_message_text(t("choose_service", lang), reply_markup=reply_markup, parse_mode="HTML")
    return MENU


# ==================== CONVERSATION HANDLERLAR ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/start — ro'yxatdan o'tganlarni to'g'ridan-to'g'ri menyuga, yangilarni til tanlashga yo'naltiradi."""
    tg_user = update.effective_user

    with flask_app.app_context():
        db_user = User.query.filter_by(telegram_id=tg_user.id).first()

        if db_user and db_user.is_registered():
            # ALLAQACHON RO'YXATDAN O'TGAN — ism/telefon qayta so'ralmaydi!
            context.user_data["name"] = db_user.full_name
            context.user_data["phone"] = db_user.phone
            context.user_data["lang"] = db_user.language or "kr"

            # Har safar /start bosganda ham guruh a'zoligi HAQIQATDA tekshiriladi
            # (foydalanuvchi ilgari qo'shilib, keyin guruhdan chiqib ketgan bo'lishi mumkin)
            if await is_subscribed(context.bot, tg_user.id):
                return await send_service_menu(update, context, greet=True)
            context.user_data["greet_after_subscribe"] = True
            return await send_subscription_prompt(update, context)

        if not db_user:
            db_user = User(telegram_id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name)
            db.session.add(db_user)
            db.session.commit()

    # YANGI FOYDALANUVCHI — til tanlashdan boshlanadi
    keyboard = [
        [InlineKeyboardButton("🇺🇿 O'zbekcha (lotin)", callback_data="lang_lt")],
        [InlineKeyboardButton("🇺🇿 Ўзбекча (кирилл)", callback_data="lang_kr")],
    ]
    await update.message.reply_text(
        TEXTS["choose_lang"]["kr"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return LANG


async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Til tanlangandan keyin ismni so'raydi."""
    query = update.callback_query
    await query.answer()

    lang = "lt" if query.data == "lang_lt" else "kr"
    context.user_data["lang"] = lang

    await query.edit_message_text(t("ask_name", lang), parse_mode="HTML")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ismni qabul qiladi va kontakt ulashish tugmasini chiqaradi."""
    lang = get_lang(context)
    name = update.message.text.strip()
    context.user_data["name"] = name

    keyboard = [
        [KeyboardButton(t("share_contact_btn", lang), request_contact=True)],
        [t("cancel_btn", lang)],
    ]
    await update.message.reply_text(
        t("ask_phone", lang, name=esc(name)),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Telefon raqamni (kontakt yoki matn) qabul qiladi va foydalanuvchini RO'YXATDAN O'TKAZADI (bir marta)."""
    lang = get_lang(context)

    if update.message.contact:
        phone = update.message.contact.phone_number
        if not phone.startswith("+"):
            phone = "+" + phone
    else:
        text = update.message.text.strip()
        if text == t("cancel_btn", lang):
            await update.message.reply_text(t("cancelled", lang), reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        phone = text

    context.user_data["phone"] = phone
    tg_user = update.effective_user

    with flask_app.app_context():
        db_user = User.query.filter_by(telegram_id=tg_user.id).first()
        if not db_user:
            db_user = User(telegram_id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name)
            db.session.add(db_user)
        db_user.full_name = context.user_data["name"]
        db_user.phone = phone
        db_user.language = lang
        db.session.commit()

    await update.message.reply_text(
        t("registered", lang, name=esc(context.user_data["name"]), phone=esc(phone)),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )

    # Ro'yxatdan o'tish tugadi — endi MAJBURIY guruh a'zoligi tekshiriladi.
    # Faqat haqiqatan a'zo bo'lgandan keyingina xizmatlar menyusi ochiladi.
    if await is_subscribed(context.bot, tg_user.id):
        return await send_service_menu(update, context)
    context.user_data["greet_after_subscribe"] = False
    return await send_subscription_prompt(update, context)


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """MENU holati: xizmat tanlash, ro'yxatni qayta ko'rsatish yoki bekor qilish — ism/telefon QAYTA SO'RALMAYDI."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    if query.data == "svc_cancel":
        await query.edit_message_text(t("finished", lang))
        return ConversationHandler.END

    if query.data == "svc_menu":
        # "Yana xizmat tanlash" — saqlangan ism/telefondan foydalanib ro'yxatni qayta ko'rsatadi
        return await edit_service_menu(query, context)

    # svc_<id> — xizmat tanlandi
    service_id = int(query.data.split("_")[1])
    with flask_app.app_context():
        service = Service.query.get(service_id)
        if not service:
            await query.edit_message_text(t("no_services", lang))
            return ConversationHandler.END

        context.user_data["service_id"] = service_id
        text = t(
            "confirm_text", lang,
            name=esc(context.user_data.get("name")),
            phone=esc(context.user_data.get("phone")),
            service=esc(service.name),
            duration=service.duration_minutes,
            price=f"{service.price:,.0f}",
        )

    keyboard = [
        [InlineKeyboardButton(t("confirm_btn", lang), callback_data="confirm")],
        [InlineKeyboardButton(t("back_to_services", lang), callback_data="back")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """CONFIRM holati: tasdiqlash yoki xizmatlar ro'yxatiga qaytish."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    if query.data == "back":
        return await edit_service_menu(query, context)

    # query.data == "confirm"
    tg_user = update.effective_user
    with flask_app.app_context():
        db_user = User.query.filter_by(telegram_id=tg_user.id).first()
        booking = Booking(
            user_id=db_user.id,
            service_id=context.user_data.get("service_id"),
            status=BookingStatus.PENDING,
        )
        db.session.add(booking)
        db.session.commit()

        service = Service.query.get(context.user_data.get("service_id"))
        booking_id = booking.id

        username_line = f"@{esc(tg_user.username)}" if tg_user.username else "username yo'q"
        admin_message = (
            f"🆕 <b>Yangi Qabul Talabi</b>\n\n"
            f"👤 Ism: {esc(context.user_data.get('name'))}\n"
            f"📱 Telefon: {esc(context.user_data.get('phone'))}\n"
            f"💬 Telegram: {username_line}\n"
            f"🔗 Profil: {user_mention_html(tg_user, label=context.user_data.get('name'))}\n"
            f"🏥 Xizmat: {esc(service.name)}\n"
            f"💰 Narxi: {service.price:,.0f} so'm\n\n"
            f"ID: {booking_id}\n"
            f"Vaqt: {booking.created_at.strftime('%Y-%m-%d %H:%M')}"
        )

    admin_keyboard = [[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_{booking_id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_{booking_id}"),
    ]]
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text=admin_message, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
    except Exception as e:
        logger.error(f"Admin notification xatosi: {e}")

    # Tasdiqlash xabarini ko'rsatish (tugmasiz)
    await query.edit_message_text(t("booking_success", lang, id=booking_id), parse_mode="HTML")

    # AVTOMATIK RAVISHDA xizmatlar ro'yxatiga qaytish — ism/telefon SAQLANGANCHA QOLADI
    with flask_app.app_context():
        services = Service.query.all()

    reply_markup = build_services_keyboard(lang, services)

    await query.message.reply_text(
        t("choose_service", lang),
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    return MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = get_lang(context)
    await update.message.reply_text(t("cancelled", lang), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ==================== BOSHQA BUYRUQLAR ====================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📞 <b>Jarrohlik Markazi Qo'llab-Quvvatlash</b>\n" + SEP + "\n"
        "🔹 <code>/start</code> — Qabul vaqtini band qilishni boshlash\n"
        "🔹 <code>/faq</code> — Tez-tez so'raladigan savollar ro'yxati\n"
        "🔹 <code>/help</code> — Bu xabar\n\n"
        "❓ Yoki menga oddiy savolingizni yozing — avtomatik javob beraman!",
        parse_mode="HTML"
    )


def build_faq_keyboard(faqs, lang: str) -> InlineKeyboardMarkup:
    """FAQ savollarini tugma sifatida yasaydi — tanlansa avtomatik javob chiqadi."""
    keyboard = []
    for f in faqs:
        short_q = f.question if len(f.question) <= 60 else f.question[:57] + "..."
        keyboard.append([InlineKeyboardButton(f"❓ {short_q}", callback_data=f"faqview_{f.id}")])
    keyboard.append([InlineKeyboardButton(t("faq_operator_btn", lang), callback_data="ask_operator")])
    return InlineKeyboardMarkup(keyboard)


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/faq — savollarni tugma qilib ko'rsatadi, tanlansa javobi avtomatik chiqadi."""
    lang = get_lang(context)
    with flask_app.app_context():
        faqs = FAQ.query.all()

    if not faqs:
        await update.message.reply_text(t("no_faq", lang))
        return

    await update.message.reply_text(t("faq_list_title", lang), reply_markup=build_faq_keyboard(faqs, lang), parse_mode="HTML")


async def faq_view_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foydalanuvchi FAQ ro'yxatidan savol tanlaganda — javobni avtomatik ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    data = query.data

    if data == "faqview_back":
        with flask_app.app_context():
            faqs = FAQ.query.all()
        if not faqs:
            await query.edit_message_text(t("no_faq", lang))
            return
        await query.edit_message_text(t("faq_list_title", lang), reply_markup=build_faq_keyboard(faqs, lang), parse_mode="HTML")
        return

    faq_id = int(data.rsplit("_", 1)[1])
    with flask_app.app_context():
        faq = FAQ.query.get(faq_id)

    if not faq:
        await query.edit_message_text(t("faq_not_found", lang))
        return

    context.user_data["last_question"] = faq.question
    keyboard = [
        [InlineKeyboardButton(t("faq_back_btn", lang), callback_data="faqview_back")],
        [InlineKeyboardButton(t("faq_operator_btn", lang), callback_data="ask_operator")],
    ]
    await query.edit_message_text(
        f"❓ <b>{esc(faq.question)}</b>\n" + SEP + f"\n💬 {esc(faq.answer)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Erkin matnli savolga FAQ bazasidan avtomatik javob beradi (faqat conversation faol bo'lmaganda ishlaydi)."""
    question_text = (update.message.text or "").strip()
    if not question_text:
        return

    tg_user = update.effective_user

    with flask_app.app_context():
        faqs = FAQ.query.all()

    best_faq, score = find_best_faq(question_text, faqs) if faqs else (None, 0.0)

    if best_faq and score >= FAQ_MATCH_THRESHOLD:
        context.user_data["last_question"] = question_text
        keyboard = [[InlineKeyboardButton("👨‍⚕️ Operatorga ulanish", callback_data="ask_operator")]]
        await update.message.reply_text(
            f"❓ <b>{esc(best_faq.question)}</b>\n" + SEP + f"\n💬 {esc(best_faq.answer)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    # Mos javob topilmadi — savolni operatorlar guruhiga yuborish
    display_name = context.user_data.get("name") or tg_user.first_name or "Foydalanuvchi"
    username_line = f"@{esc(tg_user.username)}" if tg_user.username else "username yo'q"
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            parse_mode="HTML",
            text=(
                f"❓ <b>Yangi savol</b> (avtomatik javob topilmadi)\n\n"
                f"👤 Ism: {esc(display_name)}\n"
                f"💬 Telegram: {username_line}\n"
                f"🔗 Profil: {user_mention_html(tg_user, label=display_name)}\n"
                f"🆔 ID: {tg_user.id}\n\n"
                f"Savol: {esc(question_text)}"
            )
        )
    except Exception as e:
        logger.error(f"Savolni operatorga yuborishda xato: {e}")

    await update.message.reply_text(
        "🙏 <b>Savolingiz uchun rahmat!</b>\nOperatorlarimiz tez orada javob berishadi.\n\n"
        "Qabul band qilish uchun /start bosing.",
        parse_mode="HTML"
    )


async def ask_operator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FAQ javobi yordam bermasa, savolni operatorlar guruhiga yuboradi."""
    query = update.callback_query
    await query.answer("Savolingiz operatorga yuborildi ✅", show_alert=True)

    tg_user = update.effective_user
    question_text = context.user_data.get("last_question", "(mavjud emas)")
    display_name = context.user_data.get("name") or tg_user.first_name or "Foydalanuvchi"
    username_line = f"@{esc(tg_user.username)}" if tg_user.username else "username yo'q"

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            parse_mode="HTML",
            text=(
                f"🙋 <b>Foydalanuvchi operator yordamini so'radi</b>\n\n"
                f"👤 Ism: {esc(display_name)}\n"
                f"💬 Telegram: {username_line}\n"
                f"🔗 Profil: {user_mention_html(tg_user, label=display_name)}\n"
                f"🆔 ID: {tg_user.id}\n\n"
                f"Savol: {esc(question_text)}"
            )
        )
    except Exception as e:
        logger.error(f"Operatorga yuborishda xato: {e}")


# ==================== MENING BRONLARIM ====================

def build_my_bookings_keyboard(bookings, lang: str) -> InlineKeyboardMarkup:
    keyboard = []
    for b in bookings:
        emoji = {"pending": "🟡", "confirmed": "🟢", "cancelled": "🔴", "completed": "✅"}.get(b.status.value, "⚪")
        svc = b.service.name if b.service else "?"
        date_str = b.created_at.strftime("%d.%m.%Y") if b.created_at else ""
        btn_text = f"{emoji} {svc} · {date_str}"
        if len(btn_text) > 60:
            btn_text = btn_text[:57] + "..."
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"myb_view_{b.id}")])
    keyboard.append([InlineKeyboardButton(t("back_to_menu_btn", lang), callback_data="mybookings_backmenu")])
    return InlineKeyboardMarkup(keyboard)


async def show_my_bookings_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foydalanuvchining o'z bronlari ro'yxatini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    tg_user = update.effective_user

    with flask_app.app_context():
        db_user = User.query.filter_by(telegram_id=tg_user.id).first()
        bookings = (
            Booking.query.filter_by(user_id=db_user.id).order_by(Booking.id.desc()).limit(30).all()
            if db_user else []
        )

    if not bookings:
        await query.edit_message_text(t("my_bookings_empty", lang))
        return

    await query.edit_message_text(t("my_bookings_title", lang), reply_markup=build_my_bookings_keyboard(bookings, lang), parse_mode="HTML")


async def show_my_booking_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bitta bronning tafsilotlarini — faqat egasi ko'ra oladi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    tg_user = update.effective_user
    booking_id = int(query.data.rsplit("_", 1)[1])

    status_labels = {"pending": "Kutilmoqda", "confirmed": "Tasdiqlangan", "cancelled": "Bekor qilingan", "completed": "Bajarilgan"}
    status_emoji = {"pending": "🟡", "confirmed": "🟢", "cancelled": "🔴", "completed": "✅"}

    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        # XAVFSIZLIK: faqat o'z bronini ko'rishi mumkin
        if not b or b.user.telegram_id != tg_user.id:
            await query.answer("Bron topilmadi.", show_alert=True)
            return

        text = t(
            "my_booking_detail", lang,
            id=b.id,
            emoji=status_emoji.get(b.status.value, "⚪"),
            status=status_labels.get(b.status.value, b.status.value),
            service=esc(b.service.name if b.service else "?"),
            price=f"{b.service.price:,.0f}" if b.service else "?",
            date=b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "",
        )
        can_cancel = b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)

    keyboard = []
    if can_cancel:
        keyboard.append([InlineKeyboardButton(t("cancel_my_booking_btn", lang), callback_data=f"myb_cancel_{booking_id}")])
    keyboard.append([InlineKeyboardButton(t("back_to_my_bookings_btn", lang), callback_data="mybookings_list")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def confirm_my_booking_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    tg_user = update.effective_user
    booking_id = int(query.data.rsplit("_", 1)[1])

    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b or b.user.telegram_id != tg_user.id:
            await query.answer("Bron topilmadi.", show_alert=True)
            return
        svc_name = b.service.name if b.service else "?"

    keyboard = [
        [InlineKeyboardButton(t("yes_cancel_btn", lang), callback_data=f"myb_cancelconfirm_{booking_id}")],
        [InlineKeyboardButton(t("no_keep_btn", lang), callback_data=f"myb_view_{booking_id}")],
    ]
    await query.edit_message_text(
        t("my_booking_cancel_confirm", lang, service=esc(svc_name)),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def do_my_booking_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mijoz o'z bronini bekor qiladi — admin guruhiga ham xabar beriladi."""
    query = update.callback_query
    lang = get_lang(context)
    tg_user = update.effective_user
    booking_id = int(query.data.rsplit("_", 1)[1])

    with flask_app.app_context():
        b = Booking.query.get(booking_id)
        if not b or b.user.telegram_id != tg_user.id:
            await query.answer("Bron topilmadi.", show_alert=True)
            return
        b.status = BookingStatus.CANCELLED
        db.session.commit()
        svc_name = b.service.name if b.service else "?"
        display_name = context.user_data.get("name") or tg_user.first_name or "Foydalanuvchi"

    await query.answer()
    await query.edit_message_text(t("my_booking_cancelled", lang))

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            parse_mode="HTML",
            text=(
                f"ℹ️ <b>Mijoz o'z bronini bekor qildi</b>\n\n"
                f"👤 {user_mention_html(tg_user, label=display_name)}\n"
                f"🏥 Xizmat: {esc(svc_name)}\n"
                f"🆔 Bron ID: {booking_id}"
            )
        )
    except Exception as e:
        logger.error(f"Bekor qilish haqida adminga xabar berishda xato: {e}")


async def back_to_menu_from_mybookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    await cleanup_stray_location(context, update.effective_chat.id)
    with flask_app.app_context():
        services = Service.query.all()
    reply_markup = build_services_keyboard(lang, services)
    await query.edit_message_text(t("choose_service", lang), reply_markup=reply_markup, parse_mode="HTML")


# ==================== BIZ HAQIMIZDA / KONTAKTLAR ====================

async def cleanup_stray_location(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """'Biz haqimizda' bo'limida yuborilgan lokatsiya xabari chatda qolib ketmasligi uchun o'chiradi."""
    msg_id = context.user_data.pop("about_location_msg_id", None)
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.debug(f"Lokatsiya xabarini o'chirishda xato (ehtimol allaqachon o'chirilgan): {e}")


async def show_about_clinic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Klinika manzili, telefon raqami, ish vaqti va (mavjud bo'lsa) xaritadagi joylashuvini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    # Oldin yuborilgan lokatsiya bo'lsa (masalan, foydalanuvchi bu bo'limga qayta kirgan bo'lsa) — avval o'chiriladi
    await cleanup_stray_location(context, update.effective_chat.id)

    with flask_app.app_context():
        info = ClinicInfo.query.first()

    not_set = t("about_not_set", lang)
    text = t(
        "about_text_filled", lang,
        address=esc(info.address if info and info.address else not_set),
        phone=esc(info.phone if info and info.phone else not_set),
        hours=esc(info.working_hours if info and info.working_hours else not_set),
    )

    keyboard = [[InlineKeyboardButton(t("back_to_menu_btn", lang), callback_data="mybookings_backmenu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    if info and info.latitude is not None and info.longitude is not None:
        try:
            sent_loc = await query.message.reply_location(latitude=info.latitude, longitude=info.longitude)
            context.user_data["about_location_msg_id"] = sent_loc.message_id
        except Exception as e:
            logger.error(f"Lokatsiya yuborishda xato: {e}")


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        booking_id = int(query.data.split("_")[1])
        with flask_app.app_context():
            booking = Booking.query.get(booking_id)
            if booking:
                booking.status = BookingStatus.CONFIRMED
                db.session.commit()
                try:
                    await context.bot.send_message(
                        chat_id=booking.user.telegram_id,
                        text="✅ Qabulingiz tasdiqlandi!\n\nOperator sizni tez orada chaqirib yuboradi. 🙏"
                    )
                except Exception as e:
                    logger.error(f"Foydalanuvchini xabardor qilishda xato: {e}")
                await query.edit_message_text(query.message.text + "\n\n✅ Tasdiqlandi.")
            else:
                await query.answer("Qabul topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Tasdiqlashda xato: {e}")


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        booking_id = int(query.data.split("_")[1])
        with flask_app.app_context():
            booking = Booking.query.get(booking_id)
            if booking:
                booking.status = BookingStatus.CANCELLED
                db.session.commit()
                try:
                    await context.bot.send_message(
                        chat_id=booking.user.telegram_id,
                        text="❌ Afsuski, qabulingiz rad etildi. Operator siz bilan bog'lanadi."
                    )
                except Exception as e:
                    logger.error(f"Foydalanuvchini xabardor qilishda xato: {e}")
                await query.edit_message_text(query.message.text + "\n\n❌ Rad etildi.")
            else:
                await query.answer("Qabul topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Rad etishda xato: {e}")


# ==================== OMMAVIY XABAR (BROADCAST) ====================
# Admin bot (admin_bot.py) faqat bazaga "pending" broadcast yozadi — chunki u mijozlar bilan
# suhbat ochmagan, ularga to'g'ridan-to'g'ri yozolmaydi. Shu bot esa fonda muntazam ravishda
# navbatni tekshirib, topilgan xabarni HAQIQIY yuboradi.

async def broadcast_worker():
    """Fonda ishlaydi: 'pending' broadcastlarni topib, barcha ro'yxatdan o'tgan mijozlarga yuboradi.

    Rasm biriktirilgan bo'lsa, uni admin_bot.py saqlagan lokal fayldan HAR BOT UCHUN QAYTA yuklaydi —
    Telegram file_id turli botlar orasida ishlamaydi, shuning uchun bayt sifatida o'qib qayta yuboriladi.
    """
    import html as _html

    while True:
        try:
            with flask_app.app_context():
                pending = BroadcastMessage.query.filter_by(status="pending").order_by(BroadcastMessage.id).first()
                broadcast_id = None
                caption = None
                image_path = None
                telegram_ids = []
                if pending:
                    users = User.query.filter(User.full_name.isnot(None), User.phone.isnot(None)).all()
                    telegram_ids = [u.telegram_id for u in users]
                    pending.status = "sending"
                    pending.total_count = len(telegram_ids)
                    db.session.commit()
                    broadcast_id = pending.id
                    image_path = pending.image_path
                    headline = _html.escape(pending.headline) if pending.headline else ""
                    body = _html.escape(pending.text)
                    caption = f"<b>{headline}</b>\n\n{body}" if headline else body

            if broadcast_id is not None:
                image_bytes = None
                if image_path and os.path.exists(image_path):
                    with open(image_path, "rb") as f:
                        image_bytes = f.read()
                elif image_path:
                    logger.warning(f"Broadcast #{broadcast_id}: rasm fayli topilmadi ({image_path})")

                sent, failed = 0, 0
                for tg_id in telegram_ids:
                    try:
                        if image_bytes:
                            if len(caption) <= 1024:
                                await application_instance.bot.send_photo(
                                    chat_id=tg_id, photo=image_bytes, caption=caption, parse_mode="HTML"
                                )
                            else:
                                # Caption 1024 belgidan uzun — rasm alohida, matn alohida yuboriladi
                                await application_instance.bot.send_photo(chat_id=tg_id, photo=image_bytes)
                                await application_instance.bot.send_message(chat_id=tg_id, text=caption, parse_mode="HTML")
                        else:
                            await application_instance.bot.send_message(chat_id=tg_id, text=caption, parse_mode="HTML")
                        sent += 1
                    except Exception as e:
                        failed += 1
                        logger.warning(f"Broadcast yuborilmadi (user {tg_id}): {e}")
                    await asyncio.sleep(0.05)  # Telegram flood-limitidan saqlanish uchun

                with flask_app.app_context():
                    bm = BroadcastMessage.query.get(broadcast_id)
                    if bm:
                        bm.status = "done"
                        bm.sent_count = sent
                        bm.failed_count = failed
                        bm.sent_at = datetime.utcnow()
                        db.session.commit()
                logger.info(f"Broadcast #{broadcast_id} yuborildi: {sent} muvaffaqiyatli, {failed} xato")
        except Exception as e:
            logger.error(f"Broadcast worker xatosi: {e}")

        await asyncio.sleep(10)  # navbatni har 10 soniyada tekshiradi


# ==================== ASOSIY DASTUR ====================

async def run_bot():
    global application_instance
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application_instance = application

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(select_language, pattern="^lang_")],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, get_phone)],
            SUBSCRIBE: [CallbackQueryHandler(verify_subscription, pattern="^check_subscription$")],
            MENU: [CallbackQueryHandler(select_service, pattern="^svc_")],
            CONFIRM: [CallbackQueryHandler(confirm_booking, pattern="^(confirm|back)$")],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("faq", faq_command))
    application.add_handler(CallbackQueryHandler(faq_view_answer, pattern="^faqview_"))
    application.add_handler(CallbackQueryHandler(admin_approve, pattern="^approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(ask_operator, pattern="^ask_operator$"))
    # Mening bronlarim
    application.add_handler(CallbackQueryHandler(show_my_bookings_list, pattern="^mybookings_list$"))
    application.add_handler(CallbackQueryHandler(back_to_menu_from_mybookings, pattern="^mybookings_backmenu$"))
    application.add_handler(CallbackQueryHandler(show_my_booking_detail, pattern="^myb_view_"))
    application.add_handler(CallbackQueryHandler(do_my_booking_cancel, pattern="^myb_cancelconfirm_"))
    application.add_handler(CallbackQueryHandler(confirm_my_booking_cancel, pattern="^myb_cancel_"))
    # Biz haqimizda
    application.add_handler(CallbackQueryHandler(show_about_clinic, pattern="^about_clinic$"))
    # Erkin matnli savollarga avtomatik javob — faqat conversation FAOL BO'LMAGANDA ishlaydi
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_question))

    logger.info("Bot handlerlari ro'yxatdan o'tkazildi")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Bot ishga tushdi — polling boshlandi")

    broadcast_task = asyncio.create_task(broadcast_worker())

    try:
        await asyncio.Event().wait()  # Ctrl+C bosilguncha ishlaydi
    finally:
        logger.info("Bot to'xtatilmoqda...")
        broadcast_task.cancel()
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
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
