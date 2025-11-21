import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select, desc, func
from database import AsyncSessionLocal, User, TemperatureData, Settings, SystemStatus
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
class AuthStates(StatesGroup):
    waiting_for_code = State()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌡️ Температура"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📡 Статус датчика"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🔔 Уведомления")]
        ],
        resize_keyboard=True
    )

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 час", callback_data="stats_1"),
            InlineKeyboardButton(text="6 часов", callback_data="stats_6")
        ],
        [
            InlineKeyboardButton(text="24 часа", callback_data="stats_24"),
            InlineKeyboardButton(text="7 дней", callback_data="stats_168")
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")]
    ])

def get_settings_keyboard(current_interval):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱️ Интервал чтения", callback_data="show_intervals")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")]
    ])

def get_interval_keyboard(current_interval):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="30с" + (" ✓" if current_interval == "30" else ""), callback_data="interval_30"),
            InlineKeyboardButton(text="60с" + (" ✓" if current_interval == "60" else ""), callback_data="interval_60")
        ],
        [
            InlineKeyboardButton(text="5мин" + (" ✓" if current_interval == "300" else ""), callback_data="interval_300"),
            InlineKeyboardButton(text="10мин" + (" ✓" if current_interval == "600" else ""), callback_data="interval_600")
        ],
        [InlineKeyboardButton(text="« Назад к настройкам", callback_data="back_settings")]
    ])

def get_notifications_keyboard(enabled):
    status_text = "🔔 Вкл" if enabled else "🔕 Выкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Уведомления: {status_text}", callback_data="toggle_notifications")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")]
    ])

async def get_user_by_telegram(telegram_id):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

async def is_user_authorized(telegram_id):
    user = await get_user_by_telegram(telegram_id)
    return user is not None

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not await is_user_authorized(message.from_user.id):
        await message.answer(
            "❌ Доступ запрещен\n\n"
            "Обратитесь к администратору для получения доступа.\n"
            f"Ваш Telegram ID: `{message.from_user.id}`",
            parse_mode="Markdown"
        )
        return
    user = await get_user_by_telegram(message.from_user.id)
    await message.answer(
        f"👋 Добро пожаловать, {user.username}!\n\n"
        "🌡️ *CherrySmart* - система мониторинга температуры\n\n"
        "Используйте кнопки меню для управления:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

@router.message(F.text == "🌡️ Температура")
async def get_temperature(message: Message):
    if not await is_user_authorized(message.from_user.id):
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TemperatureData)
            .order_by(desc(TemperatureData.timestamp))
            .limit(1)
        )
        data = result.scalar_one_or_none()
        if data:
            temp = float(data.temperature)
            emoji = "🔥" if temp > 25 else "❄️" if temp < 15 else "🌡️"
            time_ago = datetime.now() - data.timestamp
            if time_ago.total_seconds() < 60:
                time_str = "только что"
            elif time_ago.total_seconds() < 3600:
                minutes = int(time_ago.total_seconds() / 60)
                time_str = f"{minutes} мин назад"
            else:
                hours = int(time_ago.total_seconds() / 3600)
                time_str = f"{hours} ч назад"
            
            await message.answer(
                f"{emoji} *Текущая температура*\n\n"
                f"🌡️ {temp:.2f}°C\n"
                f"🕐 Обновлено: {time_str}\n"
                f"📅 {data.timestamp.strftime('%d.%m.%Y %H:%M:%S')}",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Нет данных о температуре")

@router.message(F.text == "📊 Статистика")
async def show_stats_menu(message: Message):
    if not await is_user_authorized(message.from_user.id):
        return
    await message.answer(
        "📊 *Статистика температуры*\n\nВыберите период:",
        reply_markup=get_stats_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("stats_"))
async def process_stats(callback: CallbackQuery):
    if not await is_user_authorized(callback.from_user.id):
        return
    hours = int(callback.data.split("_")[1])
    async with AsyncSessionLocal() as db:
        time_threshold = datetime.now() - timedelta(hours=hours)
        result = await db.execute(
            select(
                func.min(TemperatureData.temperature).label('min_temp'),
                func.max(TemperatureData.temperature).label('max_temp'),
                func.avg(TemperatureData.temperature).label('avg_temp'),
                func.count(TemperatureData.id).label('count')
            )
            .where(TemperatureData.timestamp >= time_threshold)
        )
        stats = result.one()
        if stats.min_temp and stats.count > 0:
            period = f"{hours} ч" if hours < 24 else f"{hours//24} дн"
            min_temp = float(stats.min_temp)
            max_temp = float(stats.max_temp)
            avg_temp = float(stats.avg_temp)
            count = int(stats.count)
            temp_range = max_temp - min_temp
            text = (
                f"📊 *Статистика за {period}*\n\n"
                f"🌡️ *Температура:*\n"
                f"├ Минимальная: {min_temp:.2f}°C\n"
                f"├ Максимальная: {max_temp:.2f}°C\n"
                f"├ Средняя: {avg_temp:.2f}°C\n"
                f"└ Разброс: {temp_range:.2f}°C\n\n"
                f"📈 Измерений: {count}"
            )
            await callback.message.edit_text(
                text, 
                reply_markup=get_stats_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await callback.answer("❌ Нет данных за выбранный период", show_alert=True)

@router.message(F.text == "📡 Статус датчика")
async def show_sensor_status(message: Message):
    if not await is_user_authorized(message.from_user.id):
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
        status = result.scalar_one_or_none()
        if status:
            is_active = status.sensor_active
            if status.last_reading:
                time_since = (datetime.now() - status.last_reading).total_seconds()
                if time_since > 120:
                    is_active = False
            status_emoji = "🟢" if is_active else "🔴"
            status_text = "*Активен*" if is_active else "*Неактивен*"
            last_reading = status.last_reading.strftime('%d.%m.%Y %H:%M:%S') if status.last_reading else "Нет данных"
            text = (
                f"📡 *Статус датчика*\n\n"
                f"{status_emoji} Состояние: {status_text}\n"
                f"🕐 Последнее чтение:\n   {last_reading}"
            )
            if not is_active and status.error_message:
                text += f"\n\n⚠️ *Ошибка:*\n{status.error_message}"
            await message.answer(text, parse_mode="Markdown")
        else:
            await message.answer("❌ Информация о статусе недоступна")

@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    if not await is_user_authorized(message.from_user.id):
        return
    user = await get_user_by_telegram(message.from_user.id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.name == 'read_interval'))
        setting = result.scalar_one_or_none()
        current_interval = setting.value if setting else "60"
    intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
    interval_text = intervals.get(current_interval, f"{current_interval}с")
    role_text = "Администратор" if user.role == 'admin' else "Пользователь"
    await message.answer(
        f"⚙️ *Настройки*\n\n"
        f"👤 Роль: {role_text}\n"
        f"⏱️ Интервал чтения: {interval_text}\n\n"
        f"{'_Только администраторы могут изменять интервал_' if user.role != 'admin' else '_Вы можете изменять настройки системы_'}",
        reply_markup=get_settings_keyboard(current_interval),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "show_intervals")
async def show_intervals(callback: CallbackQuery):
    if not await is_user_authorized(callback.from_user.id):
        return
    user = await get_user_by_telegram(callback.from_user.id)
    if user.role != 'admin':
        await callback.answer("❌ Только администраторы могут изменять интервал", show_alert=True)
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.name == 'read_interval'))
        setting = result.scalar_one_or_none()
        current_interval = setting.value if setting else "60"
    await callback.message.edit_text(
        "⏱️ *Интервал чтения датчика*\n\nВыберите новый интервал:",
        reply_markup=get_interval_keyboard(current_interval),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_settings")
async def back_to_settings(callback: CallbackQuery):
    if not await is_user_authorized(callback.from_user.id):
        return
    user = await get_user_by_telegram(callback.from_user.id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.name == 'read_interval'))
        setting = result.scalar_one_or_none()
        current_interval = setting.value if setting else "60"
    intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
    interval_text = intervals.get(current_interval, f"{current_interval}с")
    role_text = "Администратор" if user.role == 'admin' else "Пользователь"
    await callback.message.edit_text(
        f"⚙️ *Настройки*\n\n"
        f"👤 Роль: {role_text}\n"
        f"⏱️ Интервал чтения: {interval_text}\n\n"
        f"{'_Только администраторы могут изменять интервал_' if user.role != 'admin' else '_Вы можете изменять настройки системы_'}",
        reply_markup=get_settings_keyboard(current_interval),
        parse_mode="Markdown"
    )

@router.message(F.text == "🔔 Уведомления")
async def show_notifications(message: Message):
    if not await is_user_authorized(message.from_user.id):
        return
    user = await get_user_by_telegram(message.from_user.id)
    status_text = "включены ✅" if user.notifications_enabled else "выключены ❌"
    await message.answer(
        f"🔔 *Уведомления*\n\n"
        f"Статус: {status_text}\n\n"
        f"_Нажмите кнопку ниже для изменения_",
        reply_markup=get_notifications_keyboard(user.notifications_enabled),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    if not await is_user_authorized(callback.from_user.id):
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            user.notifications_enabled = not user.notifications_enabled
            await db.commit()
            status = "включены ✅" if user.notifications_enabled else "выключены ❌"
            await callback.message.edit_text(
                f"🔔 *Уведомления*\n\n"
                f"Статус: {status}\n\n"
                f"_Нажмите кнопку ниже для изменения_",
                reply_markup=get_notifications_keyboard(user.notifications_enabled),
                parse_mode="Markdown"
            )
            await callback.answer(f"Уведомления {status}")
        else:
            await callback.answer("❌ Ошибка обновления настроек", show_alert=True)

@router.callback_query(F.data.startswith("interval_"))
async def change_interval(callback: CallbackQuery):
    if not await is_user_authorized(callback.from_user.id):
        return
    user = await get_user_by_telegram(callback.from_user.id)
    if user.role != 'admin':
        await callback.answer("❌ Только администраторы могут изменять интервал", show_alert=True)
        return
    interval = callback.data.split("_")[1]
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.name == 'read_interval'))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = interval
            setting.updated_at = datetime.now()
        else:
            setting = Settings(name='read_interval', value=interval)
            db.add(setting)
        await db.commit()
    intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
    await callback.answer(f"✅ Интервал изменен на {intervals.get(interval, interval)}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=get_interval_keyboard(interval))

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())