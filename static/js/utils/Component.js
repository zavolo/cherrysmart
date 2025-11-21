class Component {
  constructor(props = {}) {
    this.props = props
    this.state = {}
  }
  setState(newState) {
    this.state = { ...this.state, ...newState }
    this.update()
  }
  render() {
    return '<div>Override this</div>'
  }
  mount() {}
  unmount() {}
  update() {
    const container = document.getElementById('app')
    if (container) {
      container.innerHTML = this.render()
      this.mount()
    }
  }
}

export default Component