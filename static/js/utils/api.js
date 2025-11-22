let authToken = null;

const api = {
  async init() {
    try {
      const response = await fetch('/api/auth/session', {
        credentials: 'same-origin'
      });
      if (response.ok) {
        const data = await response.json();
        authToken = data.token;
        localStorage.setItem('authToken', authToken);
      }
    } catch (error) {
      console.error('Failed to get session token:', error);
    }
  },

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json'
    };
    const token = authToken || localStorage.getItem('authToken');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  },

  async handleResponse(response) {
    if (response.status === 401 || response.status === 403) {
      localStorage.removeItem('authToken');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    return response.json();
  },

  async get(url) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: this.getHeaders()
    });
    return this.handleResponse(response);
  },
  
  async post(url, data) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: this.getHeaders(),
      body: JSON.stringify(data)
    });
    return this.handleResponse(response);
  },
  
  async put(url, data) {
    const response = await fetch(url, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: this.getHeaders(),
      body: JSON.stringify(data)
    });
    return this.handleResponse(response);
  },
  
  async delete(url) {
    const response = await fetch(url, {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: this.getHeaders()
    });
    return this.handleResponse(response);
  }
};

export default api;