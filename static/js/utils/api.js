const api = {
  getHeaders() {
    return {
      'Content-Type': 'application/json'
    };
  },

  async handleResponse(response) {
    if (response.status === 401 || response.status === 403) {
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