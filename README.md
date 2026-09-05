# Jarrohlik Markazi — Telegram Bot

Tibbiy markaz uchun Telegram bot + Flask admin panel. Foydalanuvchilar botda xizmatlarga yoziladi, adminlar esa web-panel yoki Telegram guruh orqali yozilishlarni tasdiqlaydi/bekor qiladi.

## 📁 Loyiha tuzilishi

```
jarrohlik-bot/
├── bot.py               # Telegram bot (python-telegram-bot 20.1, polling)
├── app.py                # Flask API + admin panel
├── database.py           # SQLAlchemy modellar (User, Service, Booking, FAQ)
├── seed_database.py       # Bazani boshlang'ich ma'lumotlar bilan to'ldirish
├── requirements.txt
├── .env.example
├── .gitignore
└── templates/             # Admin panel (Bootstrap 5)
    ├── dashboard.html
    ├── bookings.html
    ├── services.html
    └── faq.html
```

## 🚀 O'rnatish

### 1. Virtual environment yaratish

```bash
python -m venv venv
venv\Scripts\activate
```

### 2. Paketlarni o'rnatish

```bash
pip install -r requirements.txt
```

### 3. `.env` faylini sozlash

`.env.example` faylidan nusxa oling:

```bash
copy .env.example .env
```

Va `.env` ichida haqiqiy qiymatlarni kiriting:

```
TELEGRAM_BOT_TOKEN=sizning_bot_tokeningiz
CHANNEL_ID=-5127216730
DATABASE_URL=sqlite:///bot.db
FLASK_ENV=development
```

> `TELEGRAM_BOT_TOKEN` ni [@BotFather](https://t.me/BotFather) orqali oling. `CHANNEL_ID` — yozilishlar haqida bildirishnoma keladigan admin guruhining ID raqami (bot shu guruhga qo'shilgan va xabar yubora oladigan bo'lishi kerak).

### 4. Bazani ishga tayyorlash

```bash
python seed_database.py
```

Natija:

```
✅ DATABASE SEED COMPLETE!
📊 Statistics:
  - Services: 5
  - FAQs: 7
  - Users: 1 (demo)
  - Bookings: 2 (demo)
```

Bu skript qayta-qayta ishga tushirilsa ham dublikat yozuv qo'shmaydi (idempotent).

### 5. Botni ishga tushirish

```bash
python bot.py
```

### 6. Admin panelni ishga tushirish (alohida terminalda)

```bash
python app.py
```

Panel: **http://localhost:5000**

Bot va admin panel bir vaqtda, ikkita alohida terminalda ishlaydi — ikkalasi ham bitta `bot.db` SQLite faylini ishlatadi.

## 🤖 Bot funksiyalari

| Buyruq / Tugma | Vazifasi |
|---|---|
| `/start` | Xush kelibsiz xabari, asosiy klaviatura |
| `/help` | Yordam matni |
| `/faq` | Ko'p so'raladigan savollar ro'yxati |
| 📋 Xizmatlarni Ko'rish | Barcha tibbiy xizmatlar ro'yxati |
| ✍️ Yozilish | Yozilish jarayonini boshlaydi (ConversationHandler) |
| ❓ Savol Berish | FAQ ro'yxati |
| 📞 Kontakt | Markaz kontakt ma'lumotlari |

### Yozilish jarayoni (ConversationHandler)

```
NAME → PHONE → SERVICE → CONFIRM
```

1. **NAME** — foydalanuvchi ismini kiritadi
2. **PHONE** — telefon raqamini kiritadi
3. **SERVICE** — inline tugmalar orqali xizmat tanlaydi
4. **CONFIRM** — ma'lumotlarni tasdiqlaydi (✅/❌)

Tasdiqlangandan so'ng:
- `Booking` bazaga `pending` statusda yoziladi
- Admin guruhiga (`CHANNEL_ID`) yozilish tafsilotlari + ✅ Tasdiqlash / ❌ Bekor qilish tugmalari bilan xabar boradi
- Admin guruhda tugmani bossa, foydalanuvchiga avtomatik natija xabari ketadi

### 5 ta xizmat

| Xizmat | Davomiylik |
|---|---|
| 🏥 Бариатрик Операция | 180 daqiqa |
| 💊 Эндокринология | 60 daqiqa |
| 🔬 Проктология | 90 daqiqa |
| 👩‍⚕️ Гинекология | 60 daqiqa |
| 👨‍⚕️ Мутахассис Консультацияси | 45 daqiqa |

## 🔌 API Endpoints

Barcha javoblar JSON: `{"success": true/false, "data": ..., "count": ...}` yoki xato holida `{"error": "..."}`.

### Bookings

| Method | Endpoint | Tavsif |
|---|---|---|
| GET | `/api/bookings` | Ro'yxat (filter: `?status=`, `?user_id=`, `?service_id=`) |
| GET | `/api/bookings/<id>` | Bitta booking |
| POST | `/api/bookings` | Yangi booking (`user_id`, `service_id` majburiy) |
| PUT | `/api/bookings/<id>` | Status/doctor_name/notes yangilash |
| DELETE | `/api/bookings/<id>` | O'chirish |

### Services

| Method | Endpoint | Tavsif |
|---|---|---|
| GET | `/api/services` | Ro'yxat |
| GET | `/api/services/<id>` | Bitta xizmat |
| POST | `/api/services` | Yangi xizmat (`name`, `price`, `duration_minutes` majburiy) |
| PUT | `/api/services/<id>` | Yangilash |
| DELETE | `/api/services/<id>` | O'chirish |

### FAQ

| Method | Endpoint | Tavsif |
|---|---|---|
| GET | `/api/faq` | Ro'yxat (filter: `?category=`) |
| GET | `/api/faq/<id>` | Bitta FAQ |
| POST | `/api/faq` | Yangi FAQ (`question`, `answer`, `category` majburiy) |
| PUT | `/api/faq/<id>` | Yangilash |
| DELETE | `/api/faq/<id>` | O'chirish |

`category` qiymatlari: `timing`, `booking`, `pricing`, `recovery`, `insurance`, `preparation`

### Users

| Method | Endpoint | Tavsif |
|---|---|---|
| GET | `/api/users` | Ro'yxat |
| GET | `/api/users/<id>` | Bitta foydalanuvchi |

### Health

| Method | Endpoint | Tavsif |
|---|---|---|
| GET | `/api/health` | Server holati |

## 🖥️ Admin Panel Sahifalari

| URL | Sahifa |
|---|---|
| `/` | Dashboard (statistika + tezkor havolalar) |
| `/bookings` | Bookinglar jadvali (tasdiqlash/bekor qilish/o'chirish) |
| `/services` | Xizmatlarni boshqarish (qo'shish/o'chirish) |
| `/faq` | FAQlarni boshqarish (kategoriya bo'yicha filtr) |

Barcha sahifalar **Bootstrap 5** (CDN) asosida, responsive.

## 🛠️ Troubleshooting

**`RuntimeError: There is no current event loop in thread 'MainThread'`**
Bu Python 3.12+ / 3.14'da `python-telegram-bot`ning eski `run_polling()` usuli bilan yuzaga keladigan muammo. `bot.py` bu holatni allaqachon hisobga oladi — `run_polling()` o'rniga `asyncio.run(run_bot())` ichida Application qo'lda (`async with application: ... await application.updater.start_polling()`) boshqariladi. Agar bu xato boshqa joyda chiqsa, Python versiyangizni (`python --version`) va `pip show python-telegram-bot` natijasini tekshiring.

**`sqlite3.OperationalError: no such table`**
Bazani hali seed qilmagansiz yoki jadvallar yaratilmagan. `python seed_database.py` ni ishga tushiring — u `db.create_all()` ni ham chaqiradi.

**Bot javob bermayapti yoki g'alati/takroriy xatti-harakat qilyapti (masalan, kontaktni qayta so'raydi)**
- `.env` dagi `TELEGRAM_BOT_TOKEN` to'g'riligini tekshiring
- **Eng ko'p uchraydigan sabab: bir xil tokenda bir nechta `bot.py` jarayoni bir vaqtda ishlab turadi.** Telegram `getUpdates` bitta tokenga faqat bitta faol pollingchini qo'llab-quvvatlaydi; ikkinchi nusxa ishga tushsa, yangilanishlar ikki jarayon o'rtasida tasodifiy taqsimlanadi va har biri o'z xotirasida MUSTAQIL suhbat holatini saqlagani uchun bot "unutib qolgandek" yoki bir xil savolni qayta berayotgandek ko'rinadi (`Conflict: terminated by other getUpdates request` xatosi ham shundan). Yechim: barcha eski `python bot.py` terminallarini/jarayonlarini to'xtating, so'ng faqat BITTA nusxasini ishga tushiring. Windows'da tekshirish uchun:
  ```powershell
  Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' } | Select-Object ProcessId,CommandLine
  ```

**Admin guruhga xabar bormayapti**
- Bot `CHANNEL_ID` bilan ko'rsatilgan guruhga qo'shilganini tekshiring
- Guruh ID manfiy son bo'lishi kerak (masalan `-5127216730`); superguruh bo'lsa ID odatda `-100` bilan boshlanadi
- Botga guruhda xabar yuborish huquqi (admin yoki oddiy a'zo, guruh sozlamalariga qarab) berilganini tekshiring

**`instance/bot.db` topilmayapti yoki eski ma'lumotlar ko'rinyapti**
Flask-SQLAlchemy nisbiy `sqlite:///bot.db` yo'lini ishga tushirilgan joydan qat'i nazar `instance/` papkasiga joylaydi. Bazani butunlay tozalash uchun `instance/` papkasini o'chirib, `python seed_database.py` ni qayta ishga tushiring.

**Portlar band (`Address already in use`)**
`app.py` standart holda `5000`-portda ishlaydi. Band bo'lsa, `app.run(...)` chaqiruvidagi `port=5000` qiymatini o'zgartiring yoki band qilib turgan jarayonni to'xtating.

## 📦 Talab qilinadigan versiyalar

```
Flask==3.1.3
flask-cors==6.0.5
Flask-SQLAlchemy==3.1.1
python-dotenv==1.2.3
python-telegram-bot==20.1
SQLAlchemy==2.0.52
```

Python **3.10+** talab qilinadi (3.14 bilan ham test qilingan).
