class Component {
  constructor(props = {}) {
    this.props = props
    this.state = {}
    this._isMounted = false
  }
  
  setState(newState) {
    if (!this._isMounted) return
    this.state = { ...this.state, ...newState }
    this.update()
  }
  
  render() {
    return '<div>Override this</div>'
  }
  
  mount() {
    this._isMounted = true
  }
  
  unmount() {
    this._isMounted = false
  }
  
  update() {
    if (!this._isMounted) return
    const container = document.getElementById('app')
    if (container) {
      container.innerHTML = this.render()
      this.mount()
    }
  }
}

export default Component