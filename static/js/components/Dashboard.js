import Component from '../utils/Component.js'
import api from '../utils/api.js'

class Dashboard extends Component {
  constructor(props) {
    super(props)
    this.state = {
      currentTemp: null,
      stats: null,
      chartData: [],
      loading: true,
      currentPeriod: 1,
      sensorStatus: null
    }
    this.ws = null
    this.chart = null
    this.mounted = false
    this.chartCanvas = null
  }
  
  async loadData() {
    if (!this.mounted) return
    
    try {
      const [current, stats, history, status] = await Promise.all([
        api.get('/api/temperature/current'),
        api.get(`/api/temperature/stats?hours=${this.state.currentPeriod}`),
        api.get(`/api/temperature/history?hours=${this.state.currentPeriod}&limit=200`),
        api.get('/api/system/status')
      ])
      
      if (!this.mounted) return
      
      this.setState({
        currentTemp: current,
        stats: stats,
        chartData: history,
        sensorStatus: status,
        loading: false
      })
      this.updateChart()
    } catch (error) {
      console.error('Error loading data:', error)
    }
  }
  
  connectWebSocket() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    
    this.ws = new WebSocket(`ws://${window.location.host}/ws`)
    
    this.ws.onmessage = (event) => {
      if (!this.mounted) return
      
      const data = JSON.parse(event.data)
      if (data.type === 'temperature_update') {
        this.setState({ currentTemp: data })
      } else if (data.type === 'status_update') {
        this.setState({ sensorStatus: data.status })
      }
    }
    
    this.ws.onclose = () => {
      if (this.mounted) {
        setTimeout(() => {
          if (this.mounted) {
            this.connectWebSocket()
          }
        }, 3000)
      }
    }
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }
  
  initChart() {
    if (this.chart) {
      this.chart.destroy()
      this.chart = null
    }
    
    const canvas = document.getElementById('tempChart')
    if (!canvas) return
    
    this.chartCanvas = canvas
    const ctx = canvas.getContext('2d')
    
    this.chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Температура (°C)',
          data: [],
          borderColor: '#2ecc71',
          backgroundColor: 'rgba(46, 204, 113, 0.15)',
          borderWidth: 3,
          tension: 0.4,
          fill: true,
          pointRadius: 3,
          pointHoverRadius: 6,
          pointBackgroundColor: '#2ecc71',
          pointBorderColor: 'rgba(0, 0, 0, 0.3)',
          pointBorderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          y: {
            beginAtZero: false,
            grid: { 
              color: 'rgba(0, 0, 0, 0.1)',
              drawBorder: false
            },
            ticks: {
              color: 'rgba(232, 240, 238, 0.8)',
              font: { size: 12, weight: '500' }
            }
          },
          x: {
            grid: { 
              color: 'rgba(0, 0, 0, 0.05)',
              drawBorder: false
            },
            ticks: {
              color: 'rgba(232, 240, 238, 0.8)',
              font: { size: 11, weight: '500' },
              maxRotation: 45,
              minRotation: 0
            }
          }
        },
        animation: { duration: 300 },
        interaction: {
          intersect: false,
          mode: 'index'
        }
      }
    })
  }
  
  updateChart() {
    if (!this.chart || !this.mounted) return
    
    this.chart.data.labels = this.state.chartData.map(item => {
      const time = new Date(item.timestamp)
      return time.toLocaleTimeString('ru-RU', {
        hour: '2-digit',
        minute: '2-digit'
      })
    })
    this.chart.data.datasets[0].data = this.state.chartData.map(item => item.temperature)
    this.chart.update('none')
  }
  
  changePeriod(hours) {
    this.setState({ currentPeriod: hours })
    this.loadData()
  }
  
  toggleChart() {
    const container = document.getElementById('tempChartContainer')
    if (container) {
      container.style.display = container.style.display === 'none' ? 'block' : 'none'
    }
  }
  
  formatLastReading() {
    if (!this.state.sensorStatus || !this.state.sensorStatus.last_reading) {
      return '--'
    }
    const date = new Date(this.state.sensorStatus.last_reading)
    const now = Date.now()
    const diffSeconds = Math.floor((now - date.getTime()) / 1000)
    if (diffSeconds < 60) {
      return `${diffSeconds} сек назад`
    } else if (diffSeconds < 3600) {
      return `${Math.floor(diffSeconds / 60)} мин назад`
    } else if (diffSeconds < 86400) {
      return `${Math.floor(diffSeconds / 3600)} ч назад`
    } else {
      return date.toLocaleString('ru-RU')
    }
  }
  
  render() {
    if (this.state.loading) {
      return '<div class="loading">Загрузка...</div>'
    }
    const { currentTemp, stats, sensorStatus } = this.state
    const isActive = sensorStatus && sensorStatus.sensor_active
    return `
      <div class="container">
        <div class="sensor-status">
          <div class="status-indicator ${isActive ? 'active' : ''}">
            <span class="status-dot"></span>
            <span class="status-text">${isActive ? 'Датчик активен' : 'Нет связи с датчиком'}</span>
          </div>
          <span class="status-time">${this.formatLastReading()}</span>
        </div>
        <div class="info-grid">
          <div class="info-card">
            <div class="info-icon temperature">
              <i class="fas fa-temperature-high"></i>
            </div>
            <div class="info-content">
              <span class="info-label">Температура</span>
              <span class="info-value large">${currentTemp ? currentTemp.temperature.toFixed(1) : '--'}°C</span>
            </div>
          </div>
        </div>
        <div class="stats-section">
          <div class="stats-header">
            <h2><i class="fas fa-chart-bar"></i> Статистика за период</h2>
            <div class="period-selector">
              <button class="period-btn ${this.state.currentPeriod === 1 ? 'active' : ''}" data-hours="1">1ч</button>
              <button class="period-btn ${this.state.currentPeriod === 6 ? 'active' : ''}" data-hours="6">6ч</button>
              <button class="period-btn ${this.state.currentPeriod === 24 ? 'active' : ''}" data-hours="24">24ч</button>
              <button class="period-btn ${this.state.currentPeriod === 168 ? 'active' : ''}" data-hours="168">7д</button>
            </div>
          </div>
          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-icon min">
                <i class="fas fa-arrow-down"></i>
              </div>
              <span class="stat-label">Минимум</span>
              <span class="stat-value">${stats && stats.min_temp ? stats.min_temp : '--'}°C</span>
            </div>
            <div class="stat-item">
              <div class="stat-icon max">
                <i class="fas fa-arrow-up"></i>
              </div>
              <span class="stat-label">Максимум</span>
              <span class="stat-value">${stats && stats.max_temp ? stats.max_temp : '--'}°C</span>
            </div>
            <div class="stat-item">
              <div class="stat-icon avg">
                <i class="fas fa-equals"></i>
              </div>
              <span class="stat-label">Средняя</span>
              <span class="stat-value">${stats && stats.avg_temp ? stats.avg_temp : '--'}°C</span>
            </div>
          </div>
        </div>
        <div class="chart-section">
          <div class="chart-header">
            <h3><i class="fas fa-thermometer-half"></i> График температуры</h3>
            <div class="chart-controls">
              <button class="chart-btn" id="toggleChartBtn">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </div>
          <div class="chart-container" id="tempChartContainer">
            <canvas id="tempChart"></canvas>
          </div>
        </div>
      </div>
    `
  }
  
  mount() {
    this.mounted = true
    this.loadData()
    this.connectWebSocket()
    
    setTimeout(() => {
      if (this.mounted) {
        this.initChart()
      }
    }, 100)
    
    document.querySelectorAll('.period-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.changePeriod(parseInt(btn.dataset.hours))
      })
    })
    const toggleBtn = document.getElementById('toggleChartBtn')
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => this.toggleChart())
    }
  }
  
  unmount() {
    this.mounted = false
    
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    if (this.chart) {
      this.chart.destroy()
      this.chart = null
    }
    this.chartCanvas = null
  }
}

export default Dashboard