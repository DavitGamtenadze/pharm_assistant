import { Component, type ErrorInfo, type ReactNode } from 'react'

type ErrorBoundaryProps = {
  children: ReactNode
}

type ErrorBoundaryState = {
  hasError: boolean
}

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('workspace_render_failed', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-shell" style={{ padding: 32 }}>
          <h1>The workspace failed to render</h1>
          <p>
            Reload the page. If the problem continues, check the API health
            endpoint and browser console.
          </p>
        </main>
      )
    }
    return this.props.children
  }
}
