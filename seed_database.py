#!/usr/bin/env python
"""
Database seeding script for Jarrohlik Markazi bot.
Creates initial data: services, FAQs, demo user, and demo bookings.
"""

import os
import sys
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask
from database import db, User, Service, Booking, FAQ, BookingStatus

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///bot.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize database
db.init_app(app)

# Services data
SERVICES_DATA = [
    {
        "name": "🏥 Bariatrik Operatsiya",
        "description": "Og'irlik kamaytirish operatsiyasi",
        "price": 3500000,
        "duration_minutes": 180,
        "icon": "🏥"
    },
    {
        "name": "💊 Endokrinologiya",
        "description": "Endokrin tizimi kasalliklari bo'yicha mutaxassis konsultatsiyasi",
        "price": 150000,
        "duration_minutes": 60,
        "icon": "💊"
    },
    {
        "name": "🔬 Proktalogiya",
        "description": "Rektum va kolon kasalliklari bo'yicha mutaxassis yordami",
        "price": 200000,
        "duration_minutes": 90,
        "icon": "🔬"
    },
    {
        "name": "👩‍⚕️ Ginekologiya",
        "description": "Ayol sog'lig'i bo'yicha mutaxassis konsultatsiyasi",
        "price": 180000,
        "duration_minutes": 60,
        "icon": "👩‍⚕️"
    },
    {
        "name": "👨‍⚕️ Mutaxassis Konsultatsiyasi",
        "description": "Umumiy sog'lig'i bo'yicha mutaxassis yordami",
        "price": 120000,
        "duration_minutes": 45,
        "icon": "👨‍⚕️"
    }
]

# FAQ data
FAQ_DATA = [
    {
        "question": "Qabul qaysi vaqtda bo'ladi?",
        "answer": "Qabullar Dushanba dan Juma kuniga 09:00 dan 18:00 gacha bo'ladi.",
        "category": "Qabul vaqtlari"
    },
    {
        "question": "Telefon orqali qabul band qilish mumkinmi?",
        "answer": "Ha, +998712345678 raqamiga qo'ng'iroq qiling yoki botdan foydalaning.",
        "category": "Yozilish"
    },
    {
        "question": "Xizmat narxi qancha?",
        "answer": "Xizmat narxlari turli xil. Batafsil ma'lumot uchun /start buyrugisini bosing.",
        "category": "Narxi"
    },
    {
        "question": "Operatsiyadan keyin tez orada ish boshlayman?",
        "answer": "Operatsiyani turiga qarab 2-3 haftaga ish boshlashingiz mumkin.",
        "category": "Operatsiyadan keyin"
    },
    {
        "question": "OMS sertifikati qabul qilinadi?",
        "answer": "Ha, OMS sertifikati hamda boshqa sug'urta turlari qabul qilinadi.",
        "category": "OMS sertifikat"
    },
    {
        "question": "Operatsiyaga tayyorgarchilik qanday?",
        "answer": "Tayyorgarchilik to'g'risida qo'llab-quvvatlash xizmati o'z vaqtida ma'lumot beradi.",
        "category": "Tayyorgarchilik"
    },
    {
        "question": "Telegram profil orqali yozilish mumkinmi?",
        "answer": "Ha, agar telefon raqam mavjud bo'lmasa, Telegram profilengiz orqali bog'lana olamiz.",
        "category": "Telegram yozilish"
    }
]


def seed_database():
    """Seed the database with initial data."""
    with app.app_context():
        # Create tables
        db.create_all()
        print("✅ Jadvallar yaratildi")

        # Seed services
        if Service.query.count() == 0:
            for service_data in SERVICES_DATA:
                service = Service(
                    name=service_data["name"],
                    description=service_data["description"],
                    price=service_data["price"],
                    duration_minutes=service_data["duration_minutes"],
                    icon=service_data["icon"]
                )
                db.session.add(service)
            db.session.commit()
            print(f"✅ Xizmatlar: {len(SERVICES_DATA)} ta qo'shildi")
        else:
            print(f"ℹ️  Xizmatlar allaqachon mavjud ({Service.query.count()} ta)")

        # Seed FAQs
        if FAQ.query.count() == 0:
            for faq_data in FAQ_DATA:
                faq = FAQ(
                    question=faq_data["question"],
                    answer=faq_data["answer"],
                    category=faq_data["category"],
                    created_by="system"
                )
                db.session.add(faq)
            db.session.commit()
            print(f"✅ FAQ: {len(FAQ_DATA)} ta qo'shildi")
        else:
            print(f"ℹ️  FAQ allaqachon mavjud ({FAQ.query.count()} ta)")

        # Seed demo user
        if User.query.count() == 0:
            demo_user = User(
                telegram_id=123456789,
                username="abdulvositxon_eshonov",
                first_name="Abdulvositxon",
                full_name="Abdulvositxon",
                phone="+998901234567",
                language="kr"
            )
            db.session.add(demo_user)
            db.session.commit()
            print("✅ Demo foydalanuvchi yaratildi")

            # Create demo bookings
            services = Service.query.all()
            if len(services) >= 2:
                for i, service in enumerate(services[:2]):
                    booking = Booking(
                        user_id=demo_user.id,
                        service_id=service.id,
                        status=BookingStatus.PENDING
                    )
                    db.session.add(booking)
                db.session.commit()
                print("✅ Demo qabullar yaratildi")
        else:
            print(f"ℹ️  Foydalanuvchilar allaqachon mavjud ({User.query.count()} ta)")

        # Print statistics
        print("\n📊 Bazani holati:")
        print(f"  • Xizmatlar: {Service.query.count()}")
        print(f"  • FAQ: {FAQ.query.count()}")
        print(f"  • Foydalanuvchilar: {User.query.count()}")
        print(f"  • Qabullar: {Booking.query.count()}")
        print("\n✅ Tayyoq!")


if __name__ == "__main__":
    seed_database()
