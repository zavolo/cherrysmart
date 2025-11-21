import os
import asyncio
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional
from collections import defaultdict
from quart import Quart, render_template, request, jsonify, session, redirect, url_for, websocket
from quart_cors import cors
from bcrypt import checkpw, hashpw, gensalt
from sqlalchemy import select, func, desc
from sqlalchemy.exc import IntegrityError
from database import AsyncSessionLocal, User, TemperatureData, Settings, SystemStatus, init_db
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
connected_clients = set()
DS3231_ADDRESS = 0x68
TEMP_REG = 0x11
SENSOR_TIMEOUT = 120
login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

class SensorReader:
    def __init__(self):
        self.bus = None
        self.read_interval = 60
        self.is_running = False
        self.last_successful_read = None
        self.calibration_offset = 0.0
        
    async def init_bus(self):
        try:
            self.bus = SMBus(3)
            logger.info("Датчик DS3231 успешно инициализирован")
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
    
    async def save_reading(self, temperature):
        now = datetime.now()
        async with AsyncSessionLocal() as db:
            reading = TemperatureData(
                temperature=temperature,
                timestamp=now
            )
            db.add(reading)
            await db.commit()
            self.last_successful_read = now
            await self.update_status(True, None, now)
    
    async def update_status(self, active, error_msg=None, last_reading=None):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
            status = result.scalar_one_or_none()
            update_time = datetime.now()
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
    now = datetime.now()
    attempts = login_attempts[ip_address]
    attempts[:] = [attempt for attempt in attempts if now - attempt < LOCKOUT_DURATION]
    if len(attempts) >= MAX_ATTEMPTS:
        return True
    return False

def record_failed_attempt(ip_address):
    login_attempts[ip_address].append(datetime.now())

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
    return await render_template('users.html')

@app.route('/settings')
@login_required
@admin_required
async def settings_page():
    return await render_template('settings.html')

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

@app.route('/api/temperature/current')
@login_required
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
@login_required
async def get_temperature_history():
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 1000, type=int)
    async with AsyncSessionLocal() as db:
        time_threshold = datetime.now() - timedelta(hours=hours)
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
@login_required
async def get_temperature_stats():
    hours = request.args.get('hours', 24, type=int)
    async with AsyncSessionLocal() as db:
        time_threshold = datetime.now() - timedelta(hours=hours)
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
@login_required
async def get_system_status():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemStatus).where(SystemStatus.id == 1))
        status = result.scalar_one_or_none()
        if status:
            is_active = status.sensor_active
            time_since_reading = None
            if status.last_reading:
                time_since_reading = (datetime.now() - status.last_reading).total_seconds()
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

@app.route('/api/settings', methods=['GET'])
@login_required
async def get_settings():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings))
        settings = {row.name: row.value for row in result.scalars().all()}
        return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
@admin_required
async def update_settings():
    data = await request.json
    async with AsyncSessionLocal() as db:
        for name, value in data.items():
            result = await db.execute(select(Settings).where(Settings.name == name))
            setting = result.scalar_one_or_none()
            if setting:
                setting.value = str(value)
                setting.updated_at = datetime.now()
            else:
                db.add(Settings(name=name, value=str(value)))
        await db.commit()
        await broadcast_settings_update(data)
    logger.info(f"Настройки обновлены: {data}")
    return jsonify({'success': True})

@app.route('/api/users', methods=['GET'])
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
async def delete_user(user_id):
    if user_id == session['user_id']:
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
                    time_since_reading = (datetime.now() - status.last_reading).total_seconds()
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
                cutoff_date = datetime.now() - timedelta(days=retention_days)
                result = await db.execute(
                    select(TemperatureData).where(TemperatureData.timestamp < cutoff_date)
                )
                old_records = result.scalars().all()
                for record in old_records:
                    await db.delete(record)
                await db.commit()
                if old_records:
                    logger.info(f"Удалено {len(old_records)} старых записей температуры")
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