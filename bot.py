import os
import asyncio
import aiohttp
import logging
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_BASE_URL = os.getenv('API_URL')
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
user_tokens = {}

class AuthStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = None
    
    async def init(self):
        self.session = aiohttp.ClientSession()
        logger.info("API клиент инициализирован")
    
    async def close(self):
        if self.session:
            await self.session.close()
            logger.info("API клиент закрыт")
    
    async def login(self, username, password, telegram_id):
        try:
            async with self.session.post(
                f'{self.base_url}/telegram/login',
                json={'username': username, 'password': password, 'telegram_id': telegram_id}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Успешная авторизация пользователя {username}")
                    return data.get('token'), None
                else:
                    error_data = await resp.json()
                    logger.warning(f"Ошибка авторизации для {username}: {error_data.get('error')}")
                    return None, error_data.get('error', 'Ошибка авторизации')
        except Exception as e:
            logger.error(f"Ошибка при авторизации: {e}")
            return None, str(e)
    
    async def refresh_token(self, old_token):
        try:
            headers = {'Authorization': f'Bearer {old_token}'}
            async with self.session.post(f'{self.base_url}/telegram/refresh', headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info("Токен обновлен")
                    return data.get('token')
        except Exception as e:
            logger.error(f"Ошибка обновления токена: {e}")
        return None
    
    async def get(self, endpoint, token):
        headers = {'Authorization': f'Bearer {token}'}
        try:
            async with self.session.get(f'{self.base_url}{endpoint}', headers=headers) as resp:
                return await resp.json(), resp.status
        except Exception as e:
            logger.error(f"GET {endpoint} ошибка: {e}")
            return {'error': str(e)}, 500
    
    async def post(self, endpoint, token, data=None):
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            async with self.session.post(f'{self.base_url}{endpoint}', headers=headers, json=data) as resp:
                return await resp.json(), resp.status
        except Exception as e:
            logger.error(f"POST {endpoint} ошибка: {e}")
            return {'error': str(e)}, 500
    
    async def put(self, endpoint, token, data=None):
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            async with self.session.put(f'{self.base_url}{endpoint}', headers=headers, json=data) as resp:
                return await resp.json(), resp.status
        except Exception as e:
            logger.error(f"PUT {endpoint} ошибка: {e}")
            return {'error': str(e)}, 500
    
    async def delete(self, endpoint, token):
        headers = {'Authorization': f'Bearer {token}'}
        try:
            async with self.session.delete(f'{self.base_url}{endpoint}', headers=headers) as resp:
                return await resp.json(), resp.status
        except Exception as e:
            logger.error(f"DELETE {endpoint} ошибка: {e}")
            return {'error': str(e)}, 500

api = APIClient(API_BASE_URL)

async def get_user_token(telegram_id):
    return user_tokens.get(telegram_id)

async def set_user_token(telegram_id, token):
    user_tokens[telegram_id] = token
    logger.info(f"Токен сохранен для пользователя {telegram_id}")

async def remove_user_token(telegram_id):
    if telegram_id in user_tokens:
        del user_tokens[telegram_id]
        logger.info(f"Токен удален для пользователя {telegram_id}")

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌡️ Температура"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📡 Статус датчика"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🔔 Уведомления"), KeyboardButton(text="📬 Непрочитанные")],
            [KeyboardButton(text="🚪 Выйти")]
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

def get_settings_keyboard(is_admin):
    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⏱️ Интервал чтения", callback_data="show_intervals")])
    buttons.append([InlineKeyboardButton(text="🔔 Уведомления", callback_data="toggle_notifications")])
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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

def get_notification_actions(notification_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Прочитать", callback_data=f"notif_read_{notification_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"notif_delete_{notification_id}")
        ]
    ])

async def get_user_info(telegram_id):
    token = await get_user_token(telegram_id)
    if not token:
        return None
    data, status = await api.get('/telegram/me', token)
    if status == 401:
        new_token = await api.refresh_token(token)
        if new_token:
            await set_user_token(telegram_id, new_token)
            data, status = await api.get('/telegram/me', new_token)
        else:
            await remove_user_token(telegram_id)
            return None
    if status == 200:
        return data
    return None

async def check_auth(telegram_id):
    user = await get_user_info(telegram_id)
    return user is not None

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user_info(message.from_user.id)
    if not user:
        await message.answer(
            "👋 Добро пожаловать в *CherrySmart*!\n\n"
            "Для начала работы необходимо авторизоваться.\n\n"
            "Введите ваш логин:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(AuthStates.waiting_for_username)
        logger.info(f"Новый пользователь начал авторизацию: {message.from_user.id}")
        return
    token = await get_user_token(message.from_user.id)
    unread_data, _ = await api.get('/notifications/unread_count', token)
    unread_count = unread_data.get('count', 0)
    badge = f" 🔴 {unread_count}" if unread_count > 0 else ""
    await message.answer(
        f"👋 Добро пожаловать, {user['username']}!\n\n"
        "🌡️ *CherrySmart* - система мониторинга температуры\n\n"
        f"Используйте кнопки меню для управления{badge}",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    logger.info(f"Пользователь {user['username']} запустил бота")

@router.message(AuthStates.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text)
    await message.answer(
        "Теперь введите пароль:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthStates.waiting_for_password)
    try:
        await message.delete()
    except:
        pass

@router.message(AuthStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    user_data = await state.get_data()
    username = user_data.get('username')
    password = message.text
    try:
        await message.delete()
    except:
        pass
    waiting_msg = await message.answer("⏳ Авторизация...")
    token, error = await api.login(username, password, message.from_user.id)
    if token:
        await set_user_token(message.from_user.id, token)
        await state.clear()
        user = await get_user_info(message.from_user.id)
        unread_data, _ = await api.get('/notifications/unread_count', token)
        unread_count = unread_data.get('count', 0)
        badge = f" 🔴 {unread_count}" if unread_count > 0 else ""
        await waiting_msg.edit_text(
            f"✅ Авторизация успешна!\n\n"
            f"👋 Добро пожаловать, {user['username']}!\n\n"
            "🌡️ *CherrySmart* - система мониторинга температуры\n\n"
            f"Используйте кнопки меню для управления{badge}",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        logger.info(f"Успешная авторизация пользователя {username}")
    else:
        await waiting_msg.edit_text(
            f"❌ Ошибка авторизации\n\n{error}\n\n"
            "Попробуйте снова: /start"
        )
        await state.clear()
        logger.warning(f"Неудачная попытка авторизации для {username}")

@router.message(F.text == "🚪 Выйти")
async def logout(message: Message, state: FSMContext):
    await remove_user_token(message.from_user.id)
    await state.clear()
    await message.answer(
        "👋 Вы вышли из системы\n\n"
        "Для повторного входа используйте /start",
        reply_markup=ReplyKeyboardRemove()
    )
    logger.info(f"Пользователь {message.from_user.id} вышел из системы")

@router.message(F.text == "🌡️ Температура")
async def get_temperature(message: Message):
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    token = await get_user_token(message.from_user.id)
    data, status = await api.get('/temperature/current', token)
    if status == 200:
        temp = float(data['temperature'])
        timestamp = datetime.fromisoformat(data['timestamp'])
        emoji = "🔥" if temp > 25 else "❄️" if temp < 15 else "🌡️"
        time_ago = datetime.now() - timestamp.replace(tzinfo=None)
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
            f"📅 {timestamp.strftime('%d.%m.%Y %H:%M:%S')}",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Нет данных о температуре")

@router.message(F.text == "📊 Статистика")
async def show_stats_menu(message: Message):
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    await message.answer(
        "📊 *Статистика температуры*\n\nВыберите период:",
        reply_markup=get_stats_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("stats_"))
async def process_stats(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    hours = int(callback.data.split("_")[1])
    token = await get_user_token(callback.from_user.id)
    data, status = await api.get(f'/temperature/stats?hours={hours}', token)
    if status == 200:
        min_temp = float(data['min_temp'])
        max_temp = float(data['max_temp'])
        avg_temp = float(data['avg_temp'])
        temp_range = max_temp - min_temp
        period = f"{hours} ч" if hours < 24 else f"{hours//24} дн"
        text = (
            f"📊 *Статистика за {period}*\n\n"
            f"🌡️ *Температура:*\n"
            f"├ Минимальная: {min_temp:.2f}°C\n"
            f"├ Максимальная: {max_temp:.2f}°C\n"
            f"├ Средняя: {avg_temp:.2f}°C\n"
            f"└ Разброс: {temp_range:.2f}°C"
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
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    token = await get_user_token(message.from_user.id)
    data, status = await api.get('/system/status', token)
    if status == 200:
        is_active = data['sensor_active']
        status_emoji = "🟢" if is_active else "🔴"
        status_text = "*Активен*" if is_active else "*Неактивен*"
        last_reading = "Нет данных"
        if data['last_reading']:
            timestamp = datetime.fromisoformat(data['last_reading'])
            last_reading = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        text = (
            f"📡 *Статус датчика*\n\n"
            f"{status_emoji} Состояние: {status_text}\n"
            f"🕐 Последнее чтение:\n   {last_reading}"
        )
        if not is_active and data.get('error_message'):
            text += f"\n\n⚠️ *Ошибка:*\n{data['error_message']}"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("❌ Информация о статусе недоступна")

@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    user = await get_user_info(message.from_user.id)
    token = await get_user_token(message.from_user.id)
    settings_data, _ = await api.get('/settings', token)
    current_interval = settings_data.get('read_interval', '60')
    temp_min = settings_data.get('temp_min', '15')
    temp_max = settings_data.get('temp_max', '30')
    intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
    interval_text = intervals.get(current_interval, f"{current_interval}с")
    role_text = "Администратор" if user['role'] == 'admin' else "Пользователь"
    notif_status = "включены ✅" if user['notifications_enabled'] else "выключены ❌"
    text = (
        f"⚙️ *Настройки*\n\n"
        f"👤 Роль: {role_text}\n"
        f"⏱️ Интервал чтения: {interval_text}\n"
        f"🌡️ Пороги: {temp_min}°C — {temp_max}°C\n"
        f"🔔 Уведомления: {notif_status}\n\n"
    )
    if user['role'] == 'admin':
        text += "_Вы можете изменять настройки системы_"
    else:
        text += "_Только администраторы могут изменять настройки_"
    await message.answer(
        text,
        reply_markup=get_settings_keyboard(user['role'] == 'admin'),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "show_intervals")
async def show_intervals(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    user = await get_user_info(callback.from_user.id)
    if user['role'] != 'admin':
        await callback.answer("❌ Только администраторы могут изменять интервал", show_alert=True)
        return
    token = await get_user_token(callback.from_user.id)
    settings_data, _ = await api.get('/settings', token)
    current_interval = settings_data.get('read_interval', '60')
    await callback.message.edit_text(
        "⏱️ *Интервал чтения датчика*\n\nВыберите новый интервал:",
        reply_markup=get_interval_keyboard(current_interval),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_settings")
async def back_to_settings(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    user = await get_user_info(callback.from_user.id)
    token = await get_user_token(callback.from_user.id)
    settings_data, _ = await api.get('/settings', token)
    current_interval = settings_data.get('read_interval', '60')
    temp_min = settings_data.get('temp_min', '15')
    temp_max = settings_data.get('temp_max', '30')
    intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
    interval_text = intervals.get(current_interval, f"{current_interval}с")
    role_text = "Администратор" if user['role'] == 'admin' else "Пользователь"
    notif_status = "включены ✅" if user['notifications_enabled'] else "выключены ❌"
    text = (
        f"⚙️ *Настройки*\n\n"
        f"👤 Роль: {role_text}\n"
        f"⏱️ Интервал чтения: {interval_text}\n"
        f"🌡️ Пороги: {temp_min}°C — {temp_max}°C\n"
        f"🔔 Уведомления: {notif_status}\n\n"
    )
    if user['role'] == 'admin':
        text += "_Вы можете изменять настройки системы_"
    else:
        text += "_Только администраторы могут изменять настройки_"
    await callback.message.edit_text(
        text,
        reply_markup=get_settings_keyboard(user['role'] == 'admin'),
        parse_mode="Markdown"
    )

@router.message(F.text == "🔔 Уведомления")
async def show_notifications_list(message: Message):
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    token = await get_user_token(message.from_user.id)
    data, status = await api.get('/notifications?limit=10', token)
    if status == 200 and data:
        text = "🔔 *Последние уведомления:*\n\n"
        for notif in data[:10]:
            type_emoji = {
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'success': '✅'
            }.get(notif['type'], 'ℹ️')
            read_status = "📖" if notif['is_read'] else "🔴"
            timestamp = datetime.fromisoformat(notif['created_at'])
            time_str = timestamp.strftime('%d.%m %H:%M')
            text += f"{read_status} {type_emoji} *{notif['title']}*\n"
            text += f"   {notif['message'][:100]}\n"
            text += f"   __{time_str}__\n\n"
        text += "Используйте кнопку 📬 для управления непрочитанными"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("📭 Нет уведомлений")

@router.message(F.text == "📬 Непрочитанные")
async def show_unread_notifications(message: Message):
    if not await check_auth(message.from_user.id):
        await message.answer("❌ Необходима авторизация. Используйте /start")
        return
    token = await get_user_token(message.from_user.id)
    data, status = await api.get('/notifications?unread_only=true&limit=5', token)
    if status == 200 and data:
        for notif in data[:5]:
            type_emoji = {
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'success': '✅'
            }.get(notif['type'], 'ℹ️')
            timestamp = datetime.fromisoformat(notif['created_at'])
            time_str = timestamp.strftime('%d.%m.%Y %H:%M')
            text = (
                f"{type_emoji} *{notif['title']}*\n\n"
                f"{notif['message']}\n\n"
                f"__{time_str}__"
            )
            await message.answer(
                text,
                reply_markup=get_notification_actions(notif['id']),
                parse_mode="Markdown"
            )
        if len(data) > 5:
            await message.answer(f"И еще {len(data) - 5} непрочитанных уведомлений...")
    else:
        await message.answer("📭 Нет непрочитанных уведомлений")

@router.callback_query(F.data.startswith("notif_read_"))
async def mark_notification_read(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    notif_id = callback.data.split("_")[2]
    token = await get_user_token(callback.from_user.id)
    _, status = await api.post(f'/notifications/{notif_id}/read', token)
    if status == 200:
        await callback.message.edit_text(
            callback.message.text + "\n\n✓ *Прочитано*",
            parse_mode="Markdown"
        )
        await callback.answer("✓ Отмечено как прочитанное")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("notif_delete_"))
async def delete_notification(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    notif_id = callback.data.split("_")[2]
    token = await get_user_token(callback.from_user.id)
    _, status = await api.delete(f'/notifications/{notif_id}', token)
    if status == 200:
        await callback.message.delete()
        await callback.answer("🗑 Уведомление удалено")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

@router.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    user = await get_user_info(callback.from_user.id)
    new_status = not user['notifications_enabled']
    token = await get_user_token(callback.from_user.id)
    _, status = await api.put(
        '/telegram/settings',
        token,
        {'notifications_enabled': new_status}
    )
    if status == 200:
        status_text = "включены ✅" if new_status else "выключены ❌"
        await callback.answer(f"Уведомления {status_text}")
        await back_to_settings(callback)
    else:
        await callback.answer("❌ Ошибка обновления настроек", show_alert=True)

@router.callback_query(F.data.startswith("interval_"))
async def change_interval(callback: CallbackQuery):
    if not await check_auth(callback.from_user.id):
        await callback.answer("❌ Необходима авторизация", show_alert=True)
        return
    user = await get_user_info(callback.from_user.id)
    if user['role'] != 'admin':
        await callback.answer("❌ Только администраторы могут изменять интервал", show_alert=True)
        return
    interval = callback.data.split("_")[1]
    token = await get_user_token(callback.from_user.id)
    _, status = await api.post('/settings', token, {'read_interval': interval})
    if status == 200:
        intervals = {"30": "30 секунд", "60": "1 минута", "300": "5 минут", "600": "10 минут"}
        await callback.answer(f"✅ Интервал изменен на {intervals.get(interval, interval)}", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=get_interval_keyboard(interval))
        logger.info(f"Администратор изменил интервал чтения на {interval}с")
    else:
        await callback.answer("❌ Ошибка изменения настроек", show_alert=True)

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()

async def notification_sender():
    sent_notifications = set()
    while True:
        try:
            await asyncio.sleep(10)
            for telegram_id, token in list(user_tokens.items()):
                try:
                    data, status = await api.get('/notifications?unread_only=true&limit=10', token)
                    if status == 200 and data:
                        for notif in data:
                            notif_key = f"{telegram_id}_{notif['id']}"
                            if notif_key not in sent_notifications:
                                type_emoji = {
                                    'info': 'ℹ️',
                                    'warning': '⚠️',
                                    'error': '❌',
                                    'success': '✅'
                                }.get(notif['type'], 'ℹ️')
                                timestamp = datetime.fromisoformat(notif['created_at'])
                                time_str = timestamp.strftime('%d.%m.%Y %H:%M')
                                text = (
                                    f"{type_emoji} *{notif['title']}*\n\n"
                                    f"{notif['message']}\n\n"
                                    f"__{time_str}__"
                                )
                                try:
                                    await bot.send_message(
                                        chat_id=telegram_id,
                                        text=text,
                                        reply_markup=get_notification_actions(notif['id']),
                                        parse_mode="Markdown"
                                    )
                                    sent_notifications.add(notif_key)
                                    logger.info(f"Отправлено уведомление пользователю {telegram_id}: {notif['title']}")
                                except Exception as e:
                                    logger.error(f"Ошибка отправки уведомления пользователю {telegram_id}: {e}")
                    if len(sent_notifications) > 1000:
                        sent_notifications.clear()
                except Exception as e:
                    logger.error(f"Ошибка проверки уведомлений для {telegram_id}: {e}")
        except Exception as e:
            logger.error(f"Критическая ошибка в notification_sender: {e}")
        await asyncio.sleep(5)

async def main():
    await api.init()
    dp.include_router(router)
    asyncio.create_task(notification_sender())
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка бота: {e}")
    finally:
        await api.close()
        logger.info("Бот остановлен")

if __name__ == '__main__':
    asyncio.run(main())