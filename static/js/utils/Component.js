class Component {
  constructor(props = {}) {
    this.props = props
    this.state = {}
    this._updateScheduled = false
  }
  
  setState(newState) {
    this.state = { ...this.state, ...newState }
    if (!this._updateScheduled) {
      this._updateScheduled = true
      requestAnimationFrame(() => {
        this._updateScheduled = false
        this.update()
      })
    }
  }
  
  render() {
    return '<div></div>'
  }
  
  mount() {}
  unmount() {}
  
  update() {
    const container = document.getElementById('app')
    if (container) {
      const scrollTop = container.scrollTop
      container.innerHTML = this.render()
      container.scrollTop = scrollTop
      this.mount()
    }
  }
}

export default Component