import logging
import os
import asyncio
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
from database import db, User, Service, Booking, FAQ, BookingStatus

# ==================== SOZLAMALAR ====================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-5127216730"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation holatlari
LANG, NAME, PHONE, MENU, CONFIRM = range(5)

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

TEXTS = {
    "choose_lang": {
        "lt": "Tilni tanlang / Тилни танланг:",
        "kr": "Тилни танланг / Tilni tanlang:",
    },
    "ask_name": {
        "lt": "Ismingizni kiriting:",
        "kr": "Исмингизни киритинг:",
    },
    "ask_phone": {
        "lt": "Rahmat, {name}! 😊\n\nEndi telefon raqamingizni pastdagi tugma orqali ulashing yoki yozib yuboring:",
        "kr": "Рахмат, {name}! 😊\n\nЭнди телефон рақамингизни пастдаги тугма орқали улашинг ёки ёзиб юборинг:",
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
        "lt": "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n👤 Ism: {name}\n📱 Telefon: {phone}",
        "kr": "✅ Рўйхатдан муваффақиятли ўтдингиз!\n\n👤 Исм: {name}\n📱 Телефон: {phone}",
    },
    "choose_service": {
        "lt": "Qaysi xizmatga yozilmoqchisiz?",
        "kr": "Қайси хизматга ёзилмоқчисиз?",
    },
    "welcome_back": {
        "lt": "Xush kelibsiz, {name}! 👋\n\nQaysi xizmatga yozilmoqchisiz?",
        "kr": "Хуш келибсиз, {name}! 👋\n\nҚайси хизматга ёзилмоқчисиз?",
    },
    "confirm_text": {
        "lt": "📋 Qabul ma'lumotlari:\n\n👤 Ism: {name}\n📱 Telefon: {phone}\n🏥 Xizmat: {service}\n⏱️ Vaqt: {duration} minut\n💰 Narxi: {price} so'm\n\nBarcha ma'lumotlar to'g'rimi?",
        "kr": "📋 Қабул маълумотлари:\n\n👤 Исм: {name}\n📱 Телефон: {phone}\n🏥 Хизмат: {service}\n⏱️ Вақт: {duration} минут\n💰 Нархи: {price} сўм\n\nБарча маълумотлар тўғрими?",
    },
    "confirm_btn": {"lt": "✅ Tasdiqlash", "kr": "✅ Тасдиқлаш"},
    "back_to_services": {"lt": "⬅️ Boshqa xizmat", "kr": "⬅️ Бошқа хизмат"},
    "booking_success": {
        "lt": "✅ Qabulingiz muvaffaqiyatli band qilindi!\n\nQabul ID: {id}\nOperator tez orada siz bilan bog'lanadi. 🙏",
        "kr": "✅ Қабулингиз муваффақиятли банд қилинди!\n\nҚабул ID: {id}\nОператор тез орада сиз билан боғланади. 🙏",
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
}


def t(key: str, lang: str, **kwargs) -> str:
    """Berilgan til uchun matnni qaytaradi (default: kirill)."""
    template = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get("kr", "")
    return template.format(**kwargs) if kwargs else template


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "kr")


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def send_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, greet: bool = False) -> int:
    """Xizmatlar ro'yxatini ko'rsatadi (yangi xabar sifatida)."""
    lang = get_lang(context)
    with flask_app.app_context():
        services = Service.query.all()

    if not services:
        text = t("no_services", lang)
        if update.callback_query:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(s.name, callback_data=f"svc_{s.id}")] for s in services]
    keyboard.append([InlineKeyboardButton(t("cancel_btn", lang), callback_data="svc_cancel")])

    if greet:
        text = t("welcome_back", lang, name=context.user_data.get("name", ""))
    else:
        text = t("choose_service", lang)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return MENU


async def edit_service_menu(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xizmatlar ro'yxatini mavjud xabarni tahrirlab ko'rsatadi."""
    lang = get_lang(context)
    with flask_app.app_context():
        services = Service.query.all()

    keyboard = [[InlineKeyboardButton(s.name, callback_data=f"svc_{s.id}")] for s in services]
    keyboard.append([InlineKeyboardButton(t("cancel_btn", lang), callback_data="svc_cancel")])

    await query.edit_message_text(t("choose_service", lang), reply_markup=InlineKeyboardMarkup(keyboard))
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
            return await send_service_menu(update, context, greet=True)

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

    await query.edit_message_text(t("ask_name", lang))
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
        t("ask_phone", lang, name=name),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
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
        t("registered", lang, name=context.user_data["name"], phone=phone),
        reply_markup=ReplyKeyboardRemove()
    )
    return await send_service_menu(update, context)


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
            name=context.user_data.get("name"),
            phone=context.user_data.get("phone"),
            service=service.name,
            duration=service.duration_minutes,
            price=f"{service.price:,.0f}",
        )

    keyboard = [
        [InlineKeyboardButton(t("confirm_btn", lang), callback_data="confirm")],
        [InlineKeyboardButton(t("back_to_services", lang), callback_data="back")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
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

        admin_message = (
            f"🆕 Yangi Qabul Talabi\n\n"
            f"👤 Ism: {context.user_data.get('name')}\n"
            f"📱 Telefon: {context.user_data.get('phone')}\n"
            f"💬 Telegram: @{tg_user.username or 'nomalum'}\n"
            f"🏥 Xizmat: {service.name}\n"
            f"⏱️ Vaqt: {service.duration_minutes} minut\n"
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
            chat_id=CHANNEL_ID, text=admin_message,
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
    except Exception as e:
        logger.error(f"Admin notification xatosi: {e}")

    # Yana xizmat tanlash imkoniyati — ism/telefon SAQLANGANCHA QOLADI
    keyboard = [
        [InlineKeyboardButton(t("another_service", lang), callback_data="svc_menu")],
        [InlineKeyboardButton(t("finish_btn", lang), callback_data="svc_cancel")],
    ]
    await query.edit_message_text(
        t("booking_success", lang, id=booking_id),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = get_lang(context)
    await update.message.reply_text(t("cancelled", lang), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ==================== BOSHQA BUYRUQLAR ====================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📞 Jarrohlik Markazi Qo'llab-Quvvatlash\n\n"
        "/start - Qabul vaqtini band qilishni boshlash\n"
        "/faq - Tez-tez so'raladigan savollar\n"
        "/help - Bu xabar"
    )


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with flask_app.app_context():
        faqs = FAQ.query.all()
    if not faqs:
        await update.message.reply_text("Hozircha FAQ mavjud emas.")
        return
    response = "❓ Tez-tez So'raladigan Savollar\n\n"
    for faq in faqs:
        response += f"Q: {faq.question}\nA: {faq.answer}\n\n"
    for i in range(0, len(response), 4000):
        await update.message.reply_text(response[i:i + 4000])


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


# ==================== ASOSIY DASTUR ====================

async def run_bot():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(select_language, pattern="^lang_")],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, get_phone)],
            MENU: [CallbackQueryHandler(select_service, pattern="^svc_")],
            CONFIRM: [CallbackQueryHandler(confirm_booking, pattern="^(confirm|back)$")],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("faq", faq_command))
    application.add_handler(CallbackQueryHandler(admin_approve, pattern="^approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))

    logger.info("Bot handlerlari ro'yxatdan o'tkazildi")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Bot ishga tushdi — polling boshlandi")

    try:
        await asyncio.Event().wait()  # Ctrl+C bosilguncha ishlaydi
    finally:
        logger.info("Bot to'xtatilmoqda...")
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