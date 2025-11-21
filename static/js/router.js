import Dashboard from './components/Dashboard.js'
import Users from './components/Users.js'
import Settings from './components/Settings.js'
import NotFound from './components/NotFound.js'

let currentComponent = null
let isTransitioning = false
let currentPath = '/'

function updateNavLinks(path) {
  document.querySelectorAll('.nav-link').forEach(link => {
    link.classList.remove('active')
    const href = link.getAttribute('href')
    if (href === path || (path === '/' && href === '/')) {
      link.classList.add('active')
    }
  })
}

function renderComponent(ComponentClass, path, props = {}) {
  if (isTransitioning) return
  isTransitioning = true
  currentPath = path
  
  const container = document.getElementById('app')
  if (!container) {
    isTransitioning = false
    return
  }
  
  updateNavLinks(path)
  
  if (currentComponent && typeof currentComponent.unmount === 'function') {
    currentComponent.unmount()
    currentComponent = null
  }
  
  container.innerHTML = ''
  
  setTimeout(() => {
    currentComponent = new ComponentClass(props)
    container.innerHTML = currentComponent.render()
    
    setTimeout(() => {
      if (currentComponent && typeof currentComponent.mount === 'function') {
        currentComponent.mount()
      }
      isTransitioning = false
    }, 50)
  }, 50)
}

page('/', () => renderComponent(Dashboard, '/'))
page('/users', () => renderComponent(Users, '/users'))
page('/settings', () => renderComponent(Settings, '/settings'))
page('*', (ctx) => renderComponent(NotFound, ctx.path))

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-link:not(.logout)').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault()
      if (isTransitioning) return
      const path = link.getAttribute('href')
      if (path === currentPath) return
      page(path)
    })
  })
  
  page()
})