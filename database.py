import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import String, Integer, Float, DateTime, Enum, BigInteger, Text, Boolean, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from bcrypt import hashpw, gensalt
load_dotenv()
DATABASE_URL = f"mysql+aiomysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum('admin', 'user'), default='user')
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
class TemperatureData(Base):
    __tablename__ = "temperature_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
class Settings(Base):
    __tablename__ = "settings"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class SystemStatus(Base):
    __tablename__ = "system_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reading: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
async def get_session():
    async with AsyncSessionLocal() as session:
        yield session
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == 'admin'))
        if not result.scalar_one_or_none():
            admin = User(
                username='admin',
                password=hashpw('admin'.encode(), gensalt()).decode(),
                role='admin'
            )
            session.add(admin)
        defaults = {
            'temp_min': '15',
            'temp_max': '30',
            'read_interval': '60',
            'sensor_timeout': '180'
        }
        for name, value in defaults.items():
            result = await session.execute(select(Settings).where(Settings.name == name))
            if not result.scalar_one_or_none():
                session.add(Settings(name=name, value=value))
        result = await session.execute(select(SystemStatus).where(SystemStatus.id == 1))
        if not result.scalar_one_or_none():
            session.add(SystemStatus(id=1, sensor_active=False))
        await session.commit()