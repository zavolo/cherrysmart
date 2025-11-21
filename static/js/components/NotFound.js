import Component from '../utils/Component.js'

class NotFound extends Component {
  render() {
    return `
      <div class="container">
        <div style="text-align: center; padding: 60px 20px;">
          <div style="font-size: 120px; margin-bottom: 20px;">404</div>
          <h1 style="margin-bottom: 16px;">Страница не найдена</h1>
          <p style="color: rgba(232,240,238,0.8); margin-bottom: 30px;">
            Запрашиваемая страница не существует
          </p>
          <a href="/" class="button primary" id="homeLink">
            <i class="fas fa-home"></i> На главную
          </a>
        </div>
      </div>
    `
  }

  mount() {
    this._isMounted = true
    const link = document.getElementById('homeLink')
    if (link) {
      link.addEventListener('click', (e) => {
        e.preventDefault()
        page('/')
      })
    }
  }
  unmount() {
    this._isMounted = false
  }
}

export default NotFound