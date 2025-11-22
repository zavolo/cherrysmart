import os
import asyncio
import logging
import jwt
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional
from collections import defaultdict
from quart import Quart, render_template, request, jsonify, session, redirect, url_for, websocket
from quart_cors import cors
from bcrypt import checkpw, hashpw, gensalt
from sqlalchemy import select, func, desc
from sqlalchemy.exc import IntegrityError
from database import AsyncSessionLocal, User, TemperatureData, Settings, SystemStatus, Notification, init_db, now_moscow
from dotenv import load_dotenv
from smbus2 import SMBus

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
app = Quart(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app = cors(app, allow_origin="*")
JWT_SECRET = os.getenv('JWT_SECRET', os.getenv('SECRET_KEY'))
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24
connected_clients = set()
DS3231_ADDRESS = 0x68
TEMP_REG = 0x11
SENSOR_TIMEOUT = 120
login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

def create_jwt_token(user_id: int, username: str, role: str) -> str:
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT токен истек")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Невалидный JWT токен")
        return None

def jwt_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        if not token:
            return jsonify({'error': 'Токен отсутствует'}), 401
        payload = verify_jwt_token(token)
        if not payload:
            return jsonify({'error': 'Невалидный или истекший токен'}), 401
        request.user_id = payload['user_id']
        request.username = payload['username']
        request.role = payload['role']
        return await f(*args, **kwargs)
    return decorated

def admin_jwt_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        if not token:
            return jsonify({'error': 'Токен отсутствует'}), 401
        payload = verify_jwt_token(token)
        if not payload:
            return jsonify({'error': 'Невалидный или истекший токен'}), 401
        if payload['role'] != 'admin':
            logger.warning(f"Попытка несанкционированного доступа от пользователя {payload['username']}")
            return jsonify({'error': 'Доступ запрещен'}), 403
        request.user_id = payload['user_id']
        request.username = payload['username']
        request.role = payload['role']
        return await f(*args, **kwargs)
    return decorated

async def create_notification(user_id: int, title: str, message: str, notif_type: str = 'info'):
    async with AsyncSessionLocal() as db:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=notif_type
        )
        db.add(notification)
        await db.commit()
        logger.info(f"Создано уведомление для пользователя {user_id}: {title}")

async def create_notification_for_all(title: str, message: str, notif_type: str = 'info', only_admins: bool = False):
    async with AsyncSessionLocal() as db:
        query = select(User).where(User.notifications_enabled == True)
        if only_admins:
            query = query.where(User.role == 'admin')
        result = await db.execute(query)
        users = result.scalars().all()
        for user in users:
            notification = Notification(
                user_id=user.id,
                title=title,
                message=message,
                type=notif_type
            )
            db.add(notification)
        await db.commit()
        logger.info(f"Создано уведомление для {len(users)} пользователей: {title}")

class SensorReader:
    def __init__(self):
        self.bus = None
        self.read_interval = 60
        self.is_running = False
        self.last_successful_read = None
        self.calibration_offset = 0.0
        self.last_alert_time = {}
        self.sensor_error_notified = False
        self.temp_thresholds_notified = {'high': False, 'low': False}
        
    async def init_bus(self):
        try:
            self.bus = SMBus(3)
            logger.info("Датчик DS3231 успешно инициализирован")
            if self.sensor_error_notified:
                await create_notification_for_all(
                    "✅ Датчик восстановлен",
                    "Связь с датчиком температуры восстановлена",
                    'success',
                    only_admins=True
                )
                self.sensor_error_notified = False
            return True
        except Exception as e:
            error_msg = f"Ошибка инициализации датчика: {str(e)}"
            logger.error(error_msg)
            await self.update_status(False, error_msg)
            return False
    
    async def read_temperature(self):
        try:
            data = self.bus.read_i2c_block_data(DS3231_ADDRESS, TEMP_REG, 2)
            raw_temp = data[0] + (data[1] >> 6) * 0.25
            calibrated_temp = raw_temp + self.calibration_offset
            return calibrated_temp
        except Exception as e:
            error_msg = f"Ошибка чтения температуры: {str(e)}"
            logger.error(error_msg)
            await self.update_status(False, error_msg)
            raise
    
    async def check_temperature_thresholds(self, temperature: float):
        async with AsyncSessionLocal() as db:
            min_result = await db.execute(select(Settings).where(Settings.name == 'temp_min'))
            max_result = await db.execute(select(Settings).where(Settings.name == 'temp_max'))
            min_setting = min_result.scalar_one_or_none()
            max_setting = max_result.scalar_one_or_none()
            if not min_setting or not max_setting:
                return
            temp_min = float(min_setting.value)
            temp_max = float(max_setting.value)
            if temperature > temp_max:
                if not self.temp_thresholds_notified['high']:
                    await create_notification_for_all(
                        "🔥 Высокая температура",
                        f"Температура превысила допустимый максимум!\nТекущая: {temperature:.1f}°C\nМаксимум: {temp_max:.1f}°C",
                        'warning'
                    )
                    self.temp_thresholds_notified['high'] = True
                    self.temp_thresholds_notified['low'] = False
            elif temperature < temp_min:
                if not self.temp_thresholds_notified['low']:
                    await create_notification_for_all(
                        "❄️ Низкая температура",
                        f"Температура ниже допустимого минимума!\nТекущая: {temperature:.1f}°C\nМинимум: {temp_min:.1f}°C",
                        'warning'
                    )
                    self.temp_thresholds_notified['low'] = True
                    self.temp_thresholds_notified['high'] = False
            else:
                if self.temp_thresholds_notified['high'] or self.temp_thresholds_notified['low']:
                    await create_notification_for_all(
                        "✅ Температура в норме",
                        f"Температура вернулась в допустимый диапазон: {temperature:.1f}°C",
                        'success'
                    )
                    self.temp_thresholds_notified['high'] = False
                    self.temp_thresholds_notified['low'] = False
    
    async def save_reading(self, temperature):
        now = now_moscow()
        async with AsyncSessionLocal() as db:
            reading = TemperatureData(
                temperature=temperature,
                timestamp=now
            )
            db.add(reading)
            await db.commit()
            self.last_successful_read = now
            await self.update_status(True, None, now)
        await self.check_temperature_thresholds(temperature)
    
    async def update_status(self, active, error_msg=None, last_reading=None):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
            status = result.scalar_one_or_none()
            update_time = now_moscow()
            if status:
                status.sensor_active = active
                status.error_message = error_msg
                status.updated_at = update_time
                if last_reading:
                    status.last_reading = last_reading
            else:
                status = SystemStatus(
                    id=1,
                    sensor_active=active,
                    error_message=error_msg,
                    last_reading=last_reading,
                    updated_at=update_time
                )
                db.add(status)
            await db.commit()
        if not active and error_msg and not self.sensor_error_notified:
            await create_notification_for_all(
                "⚠️ Ошибка датчика",
                f"Потеряна связь с датчиком температуры\n\n{error_msg}",
                'error',
                only_admins=True
            )
            self.sensor_error_notified = True
    
    async def load_settings(self):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Settings).where(Settings.name == 'read_interval'))
            setting = result.scalar_one_or_none()
            if setting:
                new_interval = int(setting.value)
                if new_interval != self.read_interval:
                    self.read_interval = new_interval
                    logger.info(f"Интервал чтения изменен на {self.read_interval}с")     
            calib_result = await db.execute(select(Settings).where(Settings.name == 'temp_calibration'))
            calib_setting = calib_result.scalar_one_or_none()
            if calib_setting:
                new_offset = float(calib_setting.value)
                if new_offset != self.calibration_offset:
                    self.calibration_offset = new_offset
                    logger.info(f"Калибровка температуры: {self.calibration_offset:+.2f}°C")
    
    async def run(self):
        retry_count = 0
        max_retries = 3
        while retry_count < max_retries:
            if await self.init_bus():
                break
            retry_count += 1
            logger.warning(f"Попытка переподключения {retry_count}/{max_retries}")
            await asyncio.sleep(10)
        if not self.bus:
            logger.error("Не удалось инициализировать датчик после всех попыток")
            return
        self.is_running = True
        logger.info(f"Запуск мониторинга температуры с интервалом {self.read_interval}с")
        consecutive_errors = 0
        while self.is_running:
            try:
                await self.load_settings()
                temp = await self.read_temperature()
                await self.save_reading(temp)
                logger.info(f"Температура: {temp:.2f}°C")
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Ошибка в цикле чтения ({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    logger.error("Слишком много ошибок подряд, попытка переподключения")
                    if self.bus:
                        try:
                            self.bus.close()
                        except:
                            pass
                        self.bus = None
                    await asyncio.sleep(5)
                    if await self.init_bus():
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(30)
                else:
                    await asyncio.sleep(5)
                continue
            await asyncio.sleep(self.read_interval)
    
    def stop(self):
        self.is_running = False
        if self.bus:
            try:
                self.bus.close()
                logger.info("Датчик остановлен")
            except:
                pass

sensor_reader = SensorReader()

def is_ip_locked(ip_address):
    now = now_moscow()
    attempts = login_attempts[ip_address]
    attempts[:] = [attempt for attempt in attempts if now - attempt < LOCKOUT_DURATION]
    if len(attempts) >= MAX_ATTEMPTS:
        return True
    return False

def record_failed_attempt(ip_address):
    login_attempts[ip_address].append(now_moscow())

def login_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return await f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == session['user_id']))
            user = result.scalar_one_or_none()
            if not user or user.role != 'admin':
                logger.warning(f"Попытка несанкционированного доступа от пользователя {session.get('username')}")
                return jsonify({'error': 'Доступ запрещен'}), 403
        return await f(*args, **kwargs)
    return decorated

@app.route('/')
@login_required
async def index():
    return await render_template('index.html')

@app.route('/users')
@login_required
@admin_required
async def users_page():
    return await render_template('index.html')

@app.route('/settings')
@login_required
@admin_required
async def settings_page():
    return await render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        client_ip = request.remote_addr
        if is_ip_locked(client_ip):
            logger.warning(f"Заблокирована попытка входа с IP {client_ip}")
            return await render_template('login.html', 
                error='Слишком много неудачных попыток. Попробуйте через 15 минут')
        form = await request.form
        username = form.get('username')
        password = form.get('password')
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user and checkpw(password.encode(), user.password.encode()):
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                login_attempts[client_ip].clear()
                logger.info(f"Успешный вход пользователя: {username} с IP {client_ip}")
                return redirect(url_for('index'))
        record_failed_attempt(client_ip)
        logger.warning(f"Неудачная попытка входа: {username} с IP {client_ip}")
        return await render_template('login.html', error='Неверные учетные данные')
    return await render_template('login.html')

@app.route('/logout')
async def logout():
    username = session.get('username')
    session.clear()
    logger.info(f"Выход пользователя: {username}")
    return redirect(url_for('login'))

@app.route('/api/auth/login', methods=['POST'])
async def web_login():
    client_ip = request.remote_addr
    if is_ip_locked(client_ip):
        logger.warning(f"Заблокирована попытка входа с IP {client_ip}")
        return jsonify({'error': 'Слишком много неудачных попыток. Попробуйте через 15 минут'}), 429
    data = await request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Необходимо указать логин и пароль'}), 400
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user and checkpw(password.encode(), user.password.encode()):
            login_attempts[client_ip].clear()
            token = create_jwt_token(user.id, user.username, user.role)
            logger.info(f"Успешный вход пользователя: {username} с IP {client_ip}")
            return jsonify({'token': token})
    record_failed_attempt(client_ip)
    logger.warning(f"Неудачная попытка входа: {username} с IP {client_ip}")
    return jsonify({'error': 'Неверные учетные данные'}), 401

@app.route('/api/telegram/login', methods=['POST'])
async def telegram_login():
    data = await request.json
    username = data.get('username')
    password = data.get('password')
    telegram_id = data.get('telegram_id')
    if not username or not password or not telegram_id:
        return jsonify({'error': 'Недостаточно данных'}), 400
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user and checkpw(password.encode(), user.password.encode()):
            user.telegram_id = telegram_id
            await db.commit()
            token = create_jwt_token(user.id, user.username, user.role)
            logger.info(f"Успешная авторизация через Telegram: {username}")
            return jsonify({'token': token})
    logger.warning(f"Неудачная попытка авторизации через Telegram: {username}")
    return jsonify({'error': 'Неверные учетные данные'}), 401

@app.route('/api/telegram/me', methods=['GET'])
@jwt_required
async def telegram_me():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == request.user_id))
        user = result.scalar_one_or_none()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        return jsonify({
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'telegram_id': user.telegram_id,
            'notifications_enabled': user.notifications_enabled,
            'created_at': user.created_at.isoformat()
        })

@app.route('/api/telegram/refresh', methods=['POST'])
@jwt_required
async def telegram_refresh():
    token = create_jwt_token(request.user_id, request.username, request.role)
    logger.info(f"Токен обновлен для пользователя {request.username}")
    return jsonify({'token': token})

@app.route('/api/telegram/settings', methods=['PUT'])
@jwt_required
async def telegram_update_settings():
    data = await request.json
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == request.user_id))
        user = result.scalar_one_or_none()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        if 'notifications_enabled' in data:
            user.notifications_enabled = data['notifications_enabled']
        await db.commit()
        logger.info(f"Настройки обновлены для пользователя {user.username}")
        return jsonify({'success': True})

@app.route('/api/temperature/current')
@jwt_required
async def get_current_temperature():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TemperatureData)
            .order_by(desc(TemperatureData.timestamp))
            .limit(1)
        )
        data = result.scalar_one_or_none()
        if data:
            return jsonify({
                'temperature': float(data.temperature),
                'timestamp': data.timestamp.isoformat()
            })
        return jsonify({'error': 'Нет данных'}), 404

@app.route('/api/temperature/history')
@jwt_required
async def get_temperature_history():
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 1000, type=int)
    async with AsyncSessionLocal() as db:
        time_threshold = now_moscow() - timedelta(hours=hours)
        result = await db.execute(
            select(TemperatureData)
            .where(TemperatureData.timestamp >= time_threshold)
            .order_by(TemperatureData.timestamp)
            .limit(limit)
        )
        data = result.scalars().all()
        return jsonify([{
            'temperature': float(row.temperature),
            'timestamp': row.timestamp.isoformat()
        } for row in data])

@app.route('/api/temperature/stats')
@jwt_required
async def get_temperature_stats():
    hours = request.args.get('hours', 24, type=int)
    async with AsyncSessionLocal() as db:
        time_threshold = now_moscow() - timedelta(hours=hours)
        result = await db.execute(
            select(
                func.min(TemperatureData.temperature).label('min_temp'),
                func.max(TemperatureData.temperature).label('max_temp'),
                func.avg(TemperatureData.temperature).label('avg_temp')
            )
            .where(TemperatureData.timestamp >= time_threshold)
        )
        stats = result.one()
        if stats.min_temp:
            return jsonify({
                'min_temp': round(float(stats.min_temp), 2),
                'max_temp': round(float(stats.max_temp), 2),
                'avg_temp': round(float(stats.avg_temp), 2)
            })
        return jsonify({'error': 'Нет данных'}), 404

@app.route('/api/system/status')
@jwt_required
async def get_system_status():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
        status = result.scalar_one_or_none()
        if status:
            is_active = status.sensor_active
            time_since_reading = None
            if status.last_reading:
                time_since_reading = (now_moscow() - status.last_reading).total_seconds()
                if time_since_reading > SENSOR_TIMEOUT:
                    is_active = False
            else:
                is_active = False
            return jsonify({
                'sensor_active': is_active,
                'last_reading': status.last_reading.isoformat() if status.last_reading else None,
                'error_message': status.error_message,
                'time_since_reading': time_since_reading if status.last_reading else None
            })
        return jsonify({
            'sensor_active': False,
            'last_reading': None,
            'error_message': 'Статус не инициализирован',
            'time_since_reading': None
        })

@app.route('/api/notifications', methods=['GET'])
@jwt_required
async def get_notifications():
    limit = request.args.get('limit', 50, type=int)
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    async with AsyncSessionLocal() as db:
        query = select(Notification).where(Notification.user_id == request.user_id)
        if unread_only:
            query = query.where(Notification.is_read == False)
        query = query.order_by(desc(Notification.created_at)).limit(limit)
        result = await db.execute(query)
        notifications = [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat()
        } for n in result.scalars().all()]
        return jsonify(notifications)

@app.route('/api/notifications/unread_count', methods=['GET'])
@jwt_required
async def get_unread_count():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count(Notification.id))
            .where(Notification.user_id == request.user_id, Notification.is_read == False)
        )
        count = result.scalar()
        return jsonify({'count': count})

@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@jwt_required
async def mark_notification_read(notification_id):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == request.user_id
            )
        )
        notification = result.scalar_one_or_none()
        if notification:
            notification.is_read = True
            await db.commit()
            return jsonify({'success': True})
        return jsonify({'error': 'Уведомление не найдено'}), 404

@app.route('/api/notifications/read_all', methods=['POST'])
@jwt_required
async def mark_all_read():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.user_id == request.user_id,
                Notification.is_read == False
            )
        )
        notifications = result.scalars().all()
        for notification in notifications:
            notification.is_read = True
        await db.commit()
        return jsonify({'success': True, 'count': len(notifications)})

@app.route('/api/notifications/<int:notification_id>', methods=['DELETE'])
@jwt_required
async def delete_notification(notification_id):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == request.user_id
            )
        )
        notification = result.scalar_one_or_none()
        if notification:
            await db.delete(notification)
            await db.commit()
            return jsonify({'success': True})
        return jsonify({'error': 'Уведомление не найдено'}), 404

@app.route('/api/settings', methods=['GET'])
@jwt_required
async def get_settings():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings))
        settings = {row.name: row.value for row in result.scalars().all()}
        return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
@admin_jwt_required
async def update_settings():
    data = await request.json
    async with AsyncSessionLocal() as db:
        for name, value in data.items():
            result = await db.execute(select(Settings).where(Settings.name == name))
            setting = result.scalar_one_or_none()
            if setting:
                setting.value = str(value)
                setting.updated_at = now_moscow()
            else:
                db.add(Settings(name=name, value=str(value)))
        await db.commit()
        await broadcast_settings_update(data)
    logger.info(f"Настройки обновлены: {data}")
    await create_notification_for_all(
        "⚙️ Настройки изменены",
        f"Администратор обновил настройки системы",
        'info',
        only_admins=True
    )
    return jsonify({'success': True})

@app.route('/api/users', methods=['GET'])
@admin_jwt_required
async def get_users():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = [{
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'telegram_id': user.telegram_id,
            'notifications_enabled': user.notifications_enabled,
            'created_at': user.created_at.isoformat()
        } for user in result.scalars().all()]
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
@admin_jwt_required
async def create_user():
    data = await request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    telegram_id = data.get('telegram_id')
    if not username or not password:
        return jsonify({'error': 'Требуется логин и пароль'}), 400
    hashed = hashpw(password.encode(), gensalt()).decode()
    try:
        async with AsyncSessionLocal() as db:
            user = User(
                username=username,
                password=hashed,
                role=role,
                telegram_id=telegram_id
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info(f"Создан новый пользователь: {username}")
            return jsonify({'success': True, 'id': user.id})
    except IntegrityError:
        logger.warning(f"Попытка создать существующего пользователя: {username}")
        return jsonify({'error': 'Юзер уже существует'}), 400

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@admin_jwt_required
async def update_user(user_id):
    data = await request.json
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return jsonify({'error': 'Юзер не найден'}), 404
        if 'password' in data and data['password']:
            user.password = hashpw(data['password'].encode(), gensalt()).decode()
        if 'role' in data:
            user.role = data['role']
        if 'telegram_id' in data:
            user.telegram_id = data['telegram_id']
        if 'notifications_enabled' in data:
            user.notifications_enabled = data['notifications_enabled']
        await db.commit()
        logger.info(f"Обновлен пользователь: {user.username}")
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_jwt_required
async def delete_user(user_id):
    if user_id == request.user_id:
        return jsonify({'error': 'Нельзя удалить самого себя'}), 400
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            username = user.username
            await db.delete(user)
            await db.commit()
            logger.info(f"Удален пользователь: {username}")
            return jsonify({'success': True})
    return jsonify({'error': 'Юзер не найден'}), 404

@app.websocket('/ws')
async def ws():
    connected_clients.add(websocket._get_current_object())
    logger.info(f"WebSocket подключение установлено. Всего клиентов: {len(connected_clients)}")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        connected_clients.discard(websocket._get_current_object())
        logger.info(f"WebSocket отключен. Осталось клиентов: {len(connected_clients)}")

async def broadcast_message(data):
    dead_clients = set()
    for client in connected_clients:
        try:
            await client.send_json(data)
        except Exception as e:
            logger.debug(f"Ошибка отправки данных клиенту: {e}")
            dead_clients.add(client)
    connected_clients.difference_update(dead_clients)

async def monitor_and_broadcast():
    logger.info("Запуск системы мониторинга и трансляции")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(TemperatureData)
                    .order_by(desc(TemperatureData.timestamp))
                    .limit(1)
                )
                data = result.scalar_one_or_none()
                status_result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
                status = status_result.scalar_one_or_none()
                is_sensor_active = False
                time_since_reading = None
                if status and status.last_reading:
                    time_since_reading = (now_moscow() - status.last_reading).total_seconds()
                    is_sensor_active = status.sensor_active and time_since_reading < SENSOR_TIMEOUT
                if data:
                    await broadcast_message({
                        'type': 'temperature_update',
                        'temperature': float(data.temperature),
                        'timestamp': data.timestamp.isoformat()
                    })
                if status:
                    await broadcast_message({
                        'type': 'status_update',
                        'status': {
                            'sensor_active': is_sensor_active,
                            'last_reading': status.last_reading.isoformat() if status.last_reading else None,
                            'error_message': status.error_message,
                            'time_since_reading': time_since_reading
                        }
                    })
        except Exception as e:
            logger.error(f"Ошибка мониторинга и трансляции: {e}")
        await asyncio.sleep(3)

async def broadcast_settings_update(settings):
    await broadcast_message({'type': 'settings_update', 'settings': settings})

async def cleanup_old_data():
    while True:
        try:
            await asyncio.sleep(86400)
            async with AsyncSessionLocal() as db:
                retention_result = await db.execute(
                    select(Settings).where(Settings.name == 'data_retention_days')
                )
                retention_setting = retention_result.scalar_one_or_none()
                retention_days = int(retention_setting.value) if retention_setting else 30
                cutoff_date = now_moscow() - timedelta(days=retention_days)
                result = await db.execute(
                    select(TemperatureData).where(TemperatureData.timestamp < cutoff_date)
                )
                old_records = result.scalars().all()
                for record in old_records:
                    await db.delete(record)
                notif_result = await db.execute(
                    select(Notification).where(
                        Notification.created_at < cutoff_date,
                        Notification.is_read == True
                    )
                )
                old_notifications = notif_result.scalars().all()
                for notif in old_notifications:
                    await db.delete(notif)
                await db.commit()
                if old_records:
                    logger.info(f"Удалено {len(old_records)} старых записей температуры")
                if old_notifications:
                    logger.info(f"Удалено {len(old_notifications)} старых уведомлений")
        except Exception as e:
            logger.error(f"Ошибка очистки старых данных: {e}")

@app.before_serving
async def startup():
    logger.info("Запуск приложения...")
    await init_db()
    async with AsyncSessionLocal() as db:
        calib_result = await db.execute(select(Settings).where(Settings.name == 'temp_calibration'))
        if not calib_result.scalar_one_or_none():
            db.add(Settings(name='temp_calibration', value='0.0'))
        retention_result = await db.execute(select(Settings).where(Settings.name == 'data_retention_days'))
        if not retention_result.scalar_one_or_none():
            db.add(Settings(name='data_retention_days', value='30'))
        await db.commit()
    asyncio.create_task(monitor_and_broadcast())
    asyncio.create_task(sensor_reader.run())
    asyncio.create_task(cleanup_old_data())
    logger.info("Приложение успешно запущено")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)