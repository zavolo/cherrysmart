import Component from '../utils/Component.js'
import api from '../utils/api.js'
import showNotification from '../utils/notification.js'

class Users extends Component {
  constructor(props) {
    super(props)
    this.state = {
      users: [],
      loading: true,
      showAddModal: false,
      showEditModal: false,
      editingUser: null,
      confirmCallback: null,
      confirmMessage: ''
    }
  }
  
  async loadUsers() {
    if (!this._isMounted) return
    try {
      const users = await api.get('/api/users')
      if (!this._isMounted) return
      this.state.users = users
      this.state.loading = false 
      const container = document.getElementById('app')
      if (container && this._isMounted) {
        container.innerHTML = this.render()
        this.attachEventListeners()
      }
    } catch (error) {
      console.error('Error loading users:', error)
    }
  }
  
  openAddModal() {
    this.state.showAddModal = true
    this.updateModals()
  }
  
  closeAddModal() {
    this.state.showAddModal = false
    this.updateModals()
    const form = document.getElementById('addUserForm')
    if (form) form.reset()
  }
  
  openEditModal(userId) {
    const user = this.state.users.find(u => u.id === userId)
    if (user) {
      this.state.showEditModal = true
      this.state.editingUser = user
      this.updateModals()
    }
  }
  
  closeEditModal() {
    this.state.showEditModal = false
    this.state.editingUser = null
    this.updateModals()
  }
  
  showConfirm(message, callback) {
    this.state.confirmMessage = message
    this.state.confirmCallback = callback
    this.updateModals()
  }
  
  closeConfirm() {
    this.state.confirmMessage = ''
    this.state.confirmCallback = null
    this.updateModals()
  }
  
  updateModals() {
    if (!this._isMounted) return
    const addModal = document.getElementById('addUserModal')
    const editModal = document.getElementById('editUserModal')
    const confirmModal = document.getElementById('confirmModal')
    if (addModal) {
      addModal.className = `modal ${this.state.showAddModal ? 'show' : ''}`
    }
    if (editModal) {
      editModal.className = `modal ${this.state.showEditModal ? 'show' : ''}`
      if (this.state.showEditModal && this.state.editingUser) {
        const form = document.getElementById('editUserForm')
        if (form) {
          form.querySelector('[name="user_id"]').value = this.state.editingUser.id
          form.querySelector('[name="username"]').value = this.state.editingUser.username
          form.querySelector('[name="role"]').value = this.state.editingUser.role
          form.querySelector('[name="telegram_id"]').value = this.state.editingUser.telegram_id || ''
          form.querySelector('[name="notifications_enabled"]').checked = this.state.editingUser.notifications_enabled
        }
      }
    }
    if (confirmModal) {
      confirmModal.className = `confirm-modal ${this.state.confirmMessage ? 'show' : ''}`
      const messageEl = document.getElementById('confirmMessage')
      if (messageEl) {
        messageEl.innerHTML = this.state.confirmMessage
      }
    }
  }
  
  async handleAddUser(e) {
    e.preventDefault()
    const formData = new FormData(e.target)
    const data = Object.fromEntries(formData)
    if (!data.telegram_id) delete data.telegram_id
    try {
      const response = await api.post('/api/users', data)      
      if (response.success) {
        this.closeAddModal()
        await this.loadUsers()
        showNotification('Юзер создан', 'success')
      } else {
        showNotification(response.error || 'Ошибка создания', 'error')
      }
    } catch (error) {
      showNotification('Ошибка создания юзера', 'error')
    }
  }

  async handleEditUser(e) {
    e.preventDefault()
    const formData = new FormData(e.target)
    const data = Object.fromEntries(formData)
    const userId = data.user_id
    delete data.user_id
    delete data.username
    if (!data.password) delete data.password
    if (!data.telegram_id) delete data.telegram_id
    data.notifications_enabled = data.notifications_enabled === 'on'
    try {
      const response = await api.put(`/api/users/${userId}`, data)
      if (response.success) {
        this.closeEditModal()
        await this.loadUsers()
        showNotification('Юзер обновлен', 'success')
      } else {
        showNotification(response.error || 'Ошибка обновления', 'error')
      }
    } catch (error) {
      showNotification('Ошибка обновления юзера', 'error')
    }
  }
  
  async deleteUser(userId, username) {
    this.showConfirm(
      `Вы уверены, что хотите удалить юзера <b>${username}</b>?`,
      async () => {
        try {
          const response = await api.delete(`/api/users/${userId}`)     
          if (response.success) {
            await this.loadUsers()
            showNotification('Пользователь удален', 'success')
          } else {
            showNotification(response.error || 'Ошибка удаления', 'error')
          }
        } catch (error) {
          showNotification('Ошибка удаления юзера', 'error')
        }
      }
    )
  }
  
  attachEventListeners() {
    if (!this._isMounted) return
    const addBtn = document.getElementById('addUserBtn')
    if (addBtn) {
      addBtn.addEventListener('click', () => this.openAddModal())
    }
    const closeAddBtn = document.getElementById('closeAddModalBtn')
    if (closeAddBtn) {
      closeAddBtn.addEventListener('click', () => this.closeAddModal())
    }
    const cancelAddBtn = document.getElementById('cancelAddBtn')
    if (cancelAddBtn) {
      cancelAddBtn.addEventListener('click', () => this.closeAddModal())
    }
    const addForm = document.getElementById('addUserForm')
    if (addForm) {
      addForm.addEventListener('submit', (e) => this.handleAddUser(e))
    }
    const closeEditBtn = document.getElementById('closeEditModalBtn')
    if (closeEditBtn) {
      closeEditBtn.addEventListener('click', () => this.closeEditModal())
    }
    const cancelEditBtn = document.getElementById('cancelEditBtn')
    if (cancelEditBtn) {
      cancelEditBtn.addEventListener('click', () => this.closeEditModal())
    }
    const editForm = document.getElementById('editUserForm')
    if (editForm) {
      editForm.addEventListener('submit', (e) => this.handleEditUser(e))
    }
    
    document.querySelectorAll('.action-btn.edit').forEach(btn => {
      btn.addEventListener('click', () => {
        this.openEditModal(parseInt(btn.dataset.userId))
      })
    })
    
    document.querySelectorAll('.action-btn.delete').forEach(btn => {
      btn.addEventListener('click', () => {
        this.deleteUser(parseInt(btn.dataset.userId), btn.dataset.username)
      })
    })
    const cancelConfirmBtn = document.getElementById('cancelConfirmBtn')
    if (cancelConfirmBtn) {
      cancelConfirmBtn.addEventListener('click', () => this.closeConfirm())
    } 
    const confirmBtn = document.getElementById('confirmBtn')
    if (confirmBtn) {
      confirmBtn.addEventListener('click', () => {
        if (this.state.confirmCallback) {
          this.state.confirmCallback()
          this.closeConfirm()
        }
      })
    }
  }
  
  render() {
    if (this.state.loading) {
      return '<div class="loading">Загрузка...</div>'
    }
    return `
      <div class="container wide">
        <div class="page-header">
          <h1><i class="fas fa-users"></i> Управление юзерами</h1>
          <button class="button primary" id="addUserBtn">
            <i class="fas fa-user-plus"></i> Добавить юзера
          </button>
        </div>
        <div class="users-table">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Логин</th>
                <th>Роль</th>
                <th>Telegram ID</th>
                <th>Уведомления</th>
                <th>Дата создания</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              ${this.state.users.map(user => `
                <tr>
                  <td>${user.id}</td>
                  <td><strong>${user.username}</strong></td>
                  <td><span class="role-badge ${user.role}">${user.role === 'admin' ? 'Админ' : 'Пользователь'}</span></td>
                  <td>${user.telegram_id || '-'}</td>
                  <td><i class="fas fa-${user.notifications_enabled ? 'check-circle' : 'times-circle'}" style="color: ${user.notifications_enabled ? '#2ecc71' : '#999'}"></i></td>
                  <td>${new Date(user.created_at).toLocaleDateString('ru-RU')}</td>
                  <td class="actions">
                    <button class="action-btn edit" data-user-id="${user.id}">
                      <i class="fas fa-edit"></i>
                    </button>
                    <button class="action-btn delete" data-user-id="${user.id}" data-username="${user.username}">
                      <i class="fas fa-trash"></i>
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
      <div id="addUserModal" class="modal ${this.state.showAddModal ? 'show' : ''}">
        <div class="modal-content">
          <div class="modal-header">
            <h2>Добавить юзера</h2>
            <button class="close-btn" id="closeAddModalBtn">&times;</button>
          </div>
          <form id="addUserForm">
            <div class="form-group">
              <label><i class="fas fa-user"></i> Логин</label>
              <input type="text" name="username" required>
            </div>
            <div class="form-group">
              <label><i class="fas fa-lock"></i> Пароль</label>
              <input type="password" name="password" required>
            </div>
            <div class="form-group">
              <label><i class="fas fa-user-tag"></i> Роль</label>
              <select name="role">
                <option value="user">Пользователь</option>
                <option value="admin">Администратор</option>
              </select>
            </div>
            <div class="form-group">
              <label><i class="fab fa-telegram"></i> Telegram ID</label>
              <input type="number" name="telegram_id" placeholder="Необязательно">
            </div>
            <div class="modal-actions">
              <button type="button" class="button secondary" id="cancelAddBtn">Отмена</button>
              <button type="submit" class="button primary">Создать</button>
            </div>
          </form>
        </div>
      </div>
      <div id="editUserModal" class="modal ${this.state.showEditModal ? 'show' : ''}">
        <div class="modal-content">
          <div class="modal-header">
            <h2>Редактировать юзера</h2>
            <button class="close-btn" id="closeEditModalBtn">&times;</button>
          </div>
          <form id="editUserForm">
            <input type="hidden" name="user_id" value="${this.state.editingUser ? this.state.editingUser.id : ''}">
            <div class="form-group">
              <label><i class="fas fa-user"></i> Логин</label>
              <input type="text" name="username" value="${this.state.editingUser ? this.state.editingUser.username : ''}" disabled>
            </div>
            <div class="form-group">
              <label><i class="fas fa-lock"></i> Новый пароль</label>
              <input type="password" name="password" placeholder="Оставьте пустым для сохранения текущего">
            </div>
            <div class="form-group">
              <label><i class="fas fa-user-tag"></i> Роль</label>
              <select name="role">
                <option value="user" ${this.state.editingUser && this.state.editingUser.role === 'user' ? 'selected' : ''}>Пользователь</option>
                <option value="admin" ${this.state.editingUser && this.state.editingUser.role === 'admin' ? 'selected' : ''}>Администратор</option>
              </select>
            </div>
            <div class="form-group">
              <label><i class="fab fa-telegram"></i> Telegram ID</label>
              <input type="number" name="telegram_id" value="${this.state.editingUser && this.state.editingUser.telegram_id ? this.state.editingUser.telegram_id : ''}" placeholder="Необязательно">
            </div>
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" name="notifications_enabled" ${this.state.editingUser && this.state.editingUser.notifications_enabled ? 'checked' : ''}>
                <span>Уведомления включены</span>
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="button secondary" id="cancelEditBtn">Отмена</button>
              <button type="submit" class="button primary">Сохранить</button>
            </div>
          </form>
        </div>
      </div>
      <div id="confirmModal" class="confirm-modal ${this.state.confirmMessage ? 'show' : ''}">
        <div class="confirm-modal-content">
          <div class="confirm-icon danger">
            <i class="fas fa-exclamation-triangle"></i>
          </div>
          <h3 class="confirm-title">Подтверждение действия</h3>
          <p class="confirm-message" id="confirmMessage">${this.state.confirmMessage}</p>
          <div class="confirm-actions">
            <button class="button secondary" id="cancelConfirmBtn">Отмена</button>
            <button class="button primary" id="confirmBtn">Удалить</button>
          </div>
        </div>
      </div>
    `
  }
  mount() {
    this._isMounted = true
    this.loadUsers()
  }
  unmount() {
    this._isMounted = false
  }
}

export default Users