import Dashboard from './components/Dashboard.js'
import Users from './components/Users.js'
import Settings from './components/Settings.js'
import NotFound from './components/NotFound.js'
let currentComponent = null

function updateNavLinks(path) {
  document.querySelectorAll('.nav-link').forEach(link => {
    link.classList.remove('active') 
    const href = link.getAttribute('href')
    if (href === path || (path === '/' && href === '/')) {
      link.classList.add('active')
    }
  })
}

function renderComponent(ComponentClass, props = {}) {
  if (currentComponent && currentComponent.unmount) {
    currentComponent.unmount()
  }
  currentComponent = new ComponentClass(props)
  const container = document.getElementById('app')
  if (container) {
    container.innerHTML = currentComponent.render() 
    if (currentComponent.mount) {
      currentComponent.mount()
    }
  } 
  updateNavLinks(window.location.pathname)
}
page('/', () => renderComponent(Dashboard))
page('/users', () => renderComponent(Users))
page('/settings', () => renderComponent(Settings))
page('*', () => renderComponent(NotFound))
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-link:not(.logout)').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault()
      const path = link.getAttribute('href')
      page(path)
    })
  })
  page()
})