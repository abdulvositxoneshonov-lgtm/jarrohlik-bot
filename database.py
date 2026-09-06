from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from enum import Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, DateTime, Text, Enum as SQLEnum, ForeignKey, Index, Boolean

db = SQLAlchemy()


class BookingStatus(str, Enum):
    """Booking status enum."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class User(db.Model):
    """User model for storing Telegram user information."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)  # Botga o'zi kiritgan ism
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(5), nullable=True)  # 'lt' yoki 'kr'
    profile_pic_url: Mapped[str] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    referral_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=True)  # Bu foydalanuvchining o'ziga xos taklif kodi
    referred_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)  # Kimning taklifi bilan kelgan (users.id)

    # Relationships
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")

    def is_registered(self):
        """User ro'yxatdan to'liq o'tganmi (ism va telefon mavjudmi)."""
        return bool(self.full_name and self.phone)

    def to_dict(self):
        """Convert user to dictionary."""
        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "first_name": self.first_name,
            "full_name": self.full_name,
            "phone": self.phone,
            "language": self.language,
            "profile_pic_url": self.profile_pic_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "bookings_count": len(self.bookings)
        }

    def __repr__(self):
        return f"<User {self.first_name} ({self.telegram_id})>"


class Service(db.Model):
    """Service model for storing medical services."""
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    icon: Mapped[str] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    bookings = relationship("Booking", back_populates="service", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert service to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price),
            "duration_minutes": self.duration_minutes,
            "icon": self.icon,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<Service {self.name}>"


class Booking(db.Model):
    """Booking model for storing service bookings."""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), nullable=False, index=True)
    doctor_name: Mapped[str] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus),
        default=BookingStatus.PENDING,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    appointment_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # Admin belgilagan qabul sanasi/vaqti
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 24 soat oldin eslatma yuborilganmi
    reminder_1h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)   # 1 soat oldin eslatma yuborilganmi
    rating: Mapped[int] = mapped_column(Integer, nullable=True)  # Mijoz qoldirgan baho (1-5)
    review_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Sharh so'rovi yuborilganmi
    # Admin guruhiga yuborilgan bildirishnoma kartochkasining joylashuvi — booking holati ADMIN BOTDA
    # o'zgartirilganda ham, aynan shu kartochkani (guruhdagi) real vaqtda yangilash uchun ishlatiladi
    group_chat_id: Mapped[int] = mapped_column(Integer, nullable=True)
    group_message_id: Mapped[int] = mapped_column(Integer, nullable=True)
    # Booking uzoq vaqt "Kutilmoqda" holatida javobsiz qolib ketsa, operatorlarga bitta marta
    # ogohlantirish eslatmasi yuborilganini belgilaydi (takror spam bo'lmasligi uchun)
    followup_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User", back_populates="bookings")
    service = relationship("Service", back_populates="bookings")

    def to_dict(self):
        """Convert booking to dictionary."""
        return {
            "id": self.id,
            "user": self.user.to_dict() if self.user else None,
            "service": self.service.to_dict() if self.service else None,
            "doctor_name": self.doctor_name,
            "notes": self.notes,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<Booking {self.id} - {self.status.value}>"


class FAQ(db.Model):
    """FAQ model for storing frequently asked questions."""
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        """Convert FAQ to dictionary."""
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<FAQ {self.id}>"


class QuickLink(db.Model):
    """Foydalanuvchiga ko'rsatiladigan tezkor havola tugmalari (masalan: Telegram guruh, Instagram, sayt)."""
    __tablename__ = "quick_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)  # Tugma matni, masalan: "💬 Chat guruhimiz"
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        """Convert quick link to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<QuickLink {self.title} -> {self.url}>"


class ClinicInfo(db.Model):
    """Klinika haqida umumiy ma'lumot ('Biz haqimizda' bo'limi uchun) — bitta qatordan iborat."""
    __tablename__ = "clinic_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(500), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)
    working_hours: Mapped[str] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert clinic info to dictionary."""
        return {
            "id": self.id,
            "address": self.address,
            "phone": self.phone,
            "working_hours": self.working_hours,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f"<ClinicInfo {self.address}>"


class BroadcastMessage(db.Model):
    """Admin panelidan yozilib, mijozlar botiga navbat orqali yuboriladigan ommaviy xabar."""
    __tablename__ = "broadcast_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    headline: Mapped[str] = mapped_column(String(200), nullable=True)   # Sarlavha (ixtiyoriy emas — har doim so'raladi)
    text: Mapped[str] = mapped_column(Text, nullable=False)              # Asosiy matn
    image_path: Mapped[str] = mapped_column(String(500), nullable=True)  # Rasm — IXTIYORIY, lokal fayl yo'li
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, sending, done
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def to_dict(self):
        """Convert broadcast message to dictionary."""
        return {
            "id": self.id,
            "headline": self.headline,
            "text": self.text,
            "image_path": self.image_path,
            "status": self.status,
            "total_count": self.total_count,
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None
        }

    def __repr__(self):
        return f"<BroadcastMessage {self.id} - {self.status}>"


# Create indexes for better query performance
__table_args__ = (
    Index("idx_user_telegram_id", User.telegram_id),
    Index("idx_service_name", Service.name),
    Index("idx_booking_user_id", Booking.user_id),
    Index("idx_booking_service_id", Booking.service_id),
    Index("idx_faq_category", FAQ.category),
)
