import {
  Activity,
  BookOpenText,
  ChevronDown,
  Files,
  RefreshCw,
} from 'lucide-react'
import type { AsyncState, HealthStatus } from '../types'

type AppHeaderProps = {
  health: HealthStatus | null
  healthState: AsyncState
  onRetryHealth: () => void
  documentCount: number
  evidenceCount: number
  openMobilePanel: 'documents' | 'evidence' | null
  onToggleMobilePanel: (panel: 'documents' | 'evidence') => void
}

function getServiceSummary(
  health: HealthStatus | null,
  state: AsyncState,
) {
  if (state === 'loading' || state === 'idle') {
    return { label: 'Connecting', tone: 'pending' }
  }

  if (state === 'error' || !health) {
    return { label: 'Service unavailable', tone: 'error' }
  }

  if (!health.openai_configured) {
    return { label: 'OpenAI not configured', tone: 'warning' }
  }

  if (!health.store_ready) {
    return { label: 'Index unavailable', tone: 'warning' }
  }

  if (health.status === 'degraded') {
    return { label: 'Service degraded', tone: 'warning' }
  }

  return { label: 'Service ready', tone: 'success' }
}

export function AppHeader({
  health,
  healthState,
  onRetryHealth,
  documentCount,
  evidenceCount,
  openMobilePanel,
  onToggleMobilePanel,
}: AppHeaderProps) {
  const service = getServiceSummary(health, healthState)

  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <BookOpenText size={20} strokeWidth={1.9} />
        </div>
        <div className="brand-copy">
          <span className="brand-name">Medical Document Assistant</span>
          <span className="brand-tagline">
            Evidence-grounded research workspace
          </span>
        </div>
      </div>

      <nav className="mobile-panel-nav" aria-label="Workspace panels">
        <button
          type="button"
          className="mobile-panel-button"
          aria-controls="documents-panel"
          aria-expanded={openMobilePanel === 'documents'}
          aria-label={`Open source library, ${documentCount} documents`}
          onClick={() => onToggleMobilePanel('documents')}
        >
          <Files size={18} />
          <span>Sources</span>
          {documentCount > 0 && (
            <span className="nav-count" aria-label={`${documentCount} documents`}>
              {documentCount}
            </span>
          )}
        </button>
        <button
          type="button"
          className="mobile-panel-button"
          aria-controls="evidence-panel"
          aria-expanded={openMobilePanel === 'evidence'}
          aria-label={`Open evidence panel, ${evidenceCount} citations`}
          onClick={() => onToggleMobilePanel('evidence')}
        >
          <BookOpenText size={18} />
          <span>Evidence</span>
          {evidenceCount > 0 && (
            <span className="nav-count" aria-label={`${evidenceCount} citations`}>
              {evidenceCount}
            </span>
          )}
        </button>
      </nav>

      <details className={`service-status service-status--${service.tone}`}>
        <summary aria-label={`${service.label}. Show service details`}>
          <span className="status-indicator" aria-hidden="true">
            <Activity size={15} />
          </span>
          <span>{service.label}</span>
          <ChevronDown className="status-chevron" size={14} aria-hidden="true" />
        </summary>
        <div className="service-popover">
          <div className="service-popover-heading">
            <div>
              <strong>Research service</strong>
              <span>Live backend health</span>
            </div>
            <span className={`health-dot health-dot--${service.tone}`} />
          </div>

          {healthState === 'success' && health ? (
            <dl className="model-list">
              <div>
                <dt>Generation</dt>
                <dd>{health.generation_model || 'Not reported'}</dd>
              </div>
              <div>
                <dt>Embeddings</dt>
                <dd>{health.embedding_model || 'Not reported'}</dd>
              </div>
              <div>
                <dt>OpenAI</dt>
                <dd>{health.openai_configured ? 'Configured' : 'Not configured'}</dd>
              </div>
              <div>
                <dt>Tracing</dt>
                <dd>{health.langfuse_enabled ? 'Langfuse enabled' : 'Local logs only'}</dd>
              </div>
              <div>
                <dt>Index</dt>
                <dd>{health.store_ready ? 'Ready' : 'Unavailable'}</dd>
              </div>
              <div>
                <dt>Documents</dt>
                <dd>{health.document_count}</dd>
              </div>
            </dl>
          ) : (
            <p className="service-message">
              {healthState === 'loading'
                ? 'Checking service health…'
                : 'The API did not respond to the health check.'}
            </p>
          )}

          {healthState === 'success' && health && !health.openai_configured && (
            <p className="service-setup-guidance">
              Add <code>OPENAI_API_KEY</code> to the API environment to enable
              generation.
            </p>
          )}

          <button
            className="text-button service-retry"
            type="button"
            onClick={onRetryHealth}
            disabled={healthState === 'loading'}
          >
            <RefreshCw
              size={14}
              className={healthState === 'loading' ? 'spin' : ''}
            />
            Check again
          </button>
        </div>
      </details>
    </header>
  )
}
