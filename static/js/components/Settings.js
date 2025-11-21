import Component from '../utils/Component.js'
import api from '../utils/api.js'
import showNotification from '../utils/notification.js'

class Settings extends Component {
  constructor(props) {
    super(props)
    this.state = {
      settings: {},
      loading: true
    }
  }
  
  async loadSettings() {
    try {
      const settings = await api.get('/api/settings')
      this.setState({ settings, loading: false })
    } catch (error) {
      console.error('Error loading settings:', error)
      showNotification('Ошибка загрузки настроек', 'error')
    }
  }
  
  async handleSubmit(e) {
    e.preventDefault()
    const formData = new FormData(e.target)
    const settings = Object.fromEntries(formData)
    if (parseFloat(settings.temp_min) >= parseFloat(settings.temp_max)) {
      showNotification('Минимальная температура должна быть меньше максимальной', 'error')
      return
    }
    try {
      const response = await api.post('/api/settings', settings) 
      if (response.success) {
        showNotification('Настройки сохранены', 'success')
      } else {
        showNotification(response.error || 'Ошибка сохранения', 'error')
      }
    } catch (error) {
      console.error('Error saving settings:', error)
      showNotification('Ошибка сохранения настроек', 'error')
    }
  }
  
  render() {
    if (this.state.loading) {
      return '<div class="loading">Загрузка...</div>'
    }
    const { settings } = this.state
    return `
      <div class="container">
        <div class="page-header">
          <h1><i class="fas fa-cog"></i> Настройки системы</h1>
        </div>
        <form id="settingsForm">
          <div class="settings-section">
            <h2><i class="fas fa-thermometer-half"></i> Пороги температуры</h2>
            <div class="settings-grid">
              <div class="form-group">
                <label>Минимальная температура (°C)</label>
                <input type="number" name="temp_min" step="0.1" value="${settings.temp_min || ''}" required>
              </div>
              <div class="form-group">
                <label>Максимальная температура (°C)</label>
                <input type="number" name="temp_max" step="0.1" value="${settings.temp_max || ''}" required>
              </div>
            </div>
          </div>
          <div class="settings-section">
            <h2><i class="fas fa-sliders-h"></i> Калибровка датчика</h2>
            <div class="settings-grid">
              <div class="form-group">
                <label>Калибровка температуры (°C)</label>
                <input type="number" name="temp_calibration" step="0.1" value="${settings.temp_calibration || '0.0'}" required>
                <small>Смещение для коррекции показаний датчика (например: -2.0 если датчик завышает на 2°C)</small>
              </div>
            </div>
          </div>
          <div class="settings-section">
            <h2><i class="fas fa-clock"></i> Интервалы</h2>
            <div class="settings-grid">
              <div class="form-group">
                <label>Интервал чтения датчика (секунды)</label>
                <input type="number" name="read_interval" min="10" max="3600" value="${settings.read_interval || ''}" required>
                <small>Рекомендуется: 30-300 секунд</small>
              </div>
              <div class="form-group">
                <label>Таймаут датчика (секунды)</label>
                <input type="number" name="sensor_timeout" min="60" max="600" value="${settings.sensor_timeout || ''}" required>
                <small>Время до предупреждения о неактивности</small>
              </div>
            </div>
          </div>
          <div class="settings-section">
            <h2><i class="fas fa-database"></i> Хранение данных</h2>
            <div class="settings-grid">
              <div class="form-group">
                <label>Срок хранения данных (дней)</label>
                <input type="number" name="data_retention_days" min="7" max="365" value="${settings.data_retention_days || '30'}" required>
                <small>Данные старше этого срока будут автоматически удаляться</small>
              </div>
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="button secondary" id="resetBtn">
              <i class="fas fa-undo"></i> Сбросить
            </button>
            <button type="submit" class="button primary">
              <i class="fas fa-save"></i> Сохранить настройки
            </button>
          </div>
        </form>
      </div>
    `
  }
  
  mount() {
    this.loadSettings()
    const form = document.getElementById('settingsForm')
    if (form) {
      form.addEventListener('submit', (e) => this.handleSubmit(e))
    } 
    const resetBtn = document.getElementById('resetBtn')
    if (resetBtn) {
      resetBtn.addEventListener('click', () => this.loadSettings())
    }
  }
  unmount() {}
}

export default Settings