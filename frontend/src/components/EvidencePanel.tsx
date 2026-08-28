import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileText,
  Layers3,
  LoaderCircle,
  Quote,
  X,
} from 'lucide-react'
import { getDocumentFileUrl, getDocumentPageImageUrl } from '../api/client'
import type { ChatTurn, Citation } from '../types'

type EvidencePanelProps = {
  activeTurn: ChatTurn | null
  activeCitationId: string | null
  isOpen: boolean
  onClose: () => void
  onSelectCitation: (citationId: string) => void
}

function getCitationTitle(citation: Citation) {
  if (citation.type === 'literature') {
    return citation.title || citation.label || 'External literature article'
  }
  return citation.title || citation.filename || citation.label || 'Document excerpt'
}

function getCitationMeta(citation: Citation) {
  if (citation.type === 'literature') {
    const source = citation.source || 'Europe PMC'
    return citation.external_id
      ? `${source} · ${citation.external_id}`
      : source
  }
  return citation.page ? `Page ${citation.page}` : 'Page not reported'
}

function DocumentPagePreview({
  documentId,
  page,
  title,
}: {
  documentId: string
  page: number
  title: string
}) {
  const previewRef = useRef<HTMLDivElement>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false

    getDocumentPageImageUrl(documentId, page)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        setImageUrl(url)
      })
      .catch(() => {
        if (!cancelled) setImageUrl(null)
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [documentId, page])

  useEffect(() => {
    previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [documentId, page])

  return (
    <div className="evidence-preview" ref={previewRef}>
      <iframe
        key={`${documentId}-${page}`}
        className="pdf-frame"
        title={`${title} page ${page}`}
        src={getDocumentFileUrl(documentId, page)}
      />
      {imageUrl ? (
        <img
          className="pdf-preview"
          src={imageUrl}
          alt={`${title} page ${page}`}
        />
      ) : null}
    </div>
  )
}

function formatScore(score: number | null) {
  if (score === null) return null
  const percentage = score <= 1 ? score * 100 : score
  return `${Math.round(percentage)}% match`
}

export function EvidencePanel({
  activeTurn,
  activeCitationId,
  isOpen,
  onClose,
  onSelectCitation,
}: EvidencePanelProps) {
  const citationRefs = useRef(new Map<string, HTMLElement>())
  const citations = activeTurn?.citations ?? []
  const activeIndex = citations.findIndex((citation) => citation.id === activeCitationId)

  const stepCitation = useCallback(
    (delta: number) => {
      if (citations.length === 0) return
      const current = activeIndex < 0 ? 0 : activeIndex
      const next = citations[(current + delta + citations.length) % citations.length]
      onSelectCitation(next.id)
    },
    [activeIndex, citations, onSelectCitation],
  )

  useEffect(() => {
    if (!activeCitationId) return
    const citation = citationRefs.current.get(activeCitationId)
    citation?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    citation?.focus({ preventScroll: true })
  }, [activeCitationId, isOpen])

  useEffect(() => {
    if (citations.length === 0) return

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) {
          return
        }
      }
      if (event.key === 'j') {
        event.preventDefault()
        stepCitation(1)
      }
      if (event.key === 'k') {
        event.preventDefault()
        stepCitation(-1)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [citations.length, stepCitation])

  return (
    <aside
      id="evidence-panel"
      className={`workspace-panel evidence-panel ${isOpen ? 'is-open' : ''}`}
      aria-label="Citation evidence"
    >
      <div className="panel-heading evidence-heading">
        <div>
          <span className="eyebrow">Source inspection</span>
          <h2>Evidence</h2>
        </div>
        <div className="evidence-heading-actions">
          {citations.length > 0 && (
            <div className="evidence-nav">
              <button
                type="button"
                className="icon-button"
                onClick={() => stepCitation(-1)}
                aria-label="Previous citation"
                title="Previous citation (k)"
              >
                <ChevronUp size={16} />
              </button>
              <span className="evidence-count">
                {`${activeIndex < 0 ? 1 : activeIndex + 1} / ${citations.length}`}
              </span>
              <button
                type="button"
                className="icon-button"
                onClick={() => stepCitation(1)}
                aria-label="Next citation"
                title="Next citation (j)"
              >
                <ChevronDown size={16} />
              </button>
            </div>
          )}
          <button
            type="button"
            className="icon-button mobile-panel-close"
            onClick={onClose}
            aria-label="Close evidence panel"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="evidence-content">
        {!activeTurn && (
          <div className="evidence-empty">
            <span className="empty-state-icon">
              <Layers3 size={25} />
            </span>
            <strong>Evidence appears here</strong>
            <p>
              Ask a question, then select a citation chip to inspect the matching
              excerpt and page.
            </p>
            <div className="evidence-explainer">
              <div>
                <span>1</span>
                <p>Select documents</p>
              </div>
              <i />
              <div>
                <span>2</span>
                <p>Ask a question</p>
              </div>
              <i />
              <div>
                <span>3</span>
                <p>Verify sources</p>
              </div>
            </div>
          </div>
        )}

        {activeTurn?.status === 'loading' && (
          <div className="evidence-loading" role="status">
            <LoaderCircle className="spin" size={22} />
            <strong>Finding supporting excerpts</strong>
            <p>Ranking document passages and literature results…</p>
          </div>
        )}

        {activeTurn?.status === 'error' && (
          <div className="evidence-empty evidence-empty--error">
            <span className="empty-state-icon">
              <AlertCircle size={24} />
            </span>
            <strong>No evidence available</strong>
            <p>The question did not complete. Retry it to retrieve source excerpts.</p>
          </div>
        )}

        {activeTurn?.status === 'success' && citations.length === 0 && (
          <div className="evidence-empty">
            <span className="empty-state-icon">
              <Quote size={24} />
            </span>
            <strong>No citations returned</strong>
            <p>
              Refine the question or broaden the selected source set before relying
              on this response.
            </p>
          </div>
        )}

        {activeTurn?.status === 'success' && citations.length > 0 && (
          <>
            <div className="evidence-summary">
              <Quote size={16} />
              <p>
                These are the passages used to ground the latest selected answer.
                Review the original source before use.
              </p>
            </div>

            <ol className="citation-list">
              {citations.map((citation, index) => {
                const isActive = citation.id === activeCitationId
                const score = formatScore(citation.score)

                return (
                  <li key={citation.id}>
                    <article
                      ref={(element) => {
                        if (element) citationRefs.current.set(citation.id, element)
                        else citationRefs.current.delete(citation.id)
                      }}
                      className={`citation-card ${isActive ? 'is-focused' : ''}`}
                      tabIndex={-1}
                      aria-label={`Citation ${index + 1}: ${getCitationTitle(citation)}`}
                    >
                      <button
                        type="button"
                        className="citation-card-main"
                        onClick={() => onSelectCitation(citation.id)}
                        aria-pressed={isActive}
                      >
                        <span className="citation-card-topline">
                          <span
                            className={`citation-type citation-type--${citation.type}`}
                          >
                            {citation.type === 'literature' ? (
                              <BookOpen size={13} />
                            ) : (
                              <FileText size={13} />
                            )}
                            {citation.type === 'literature'
                              ? 'External literature'
                              : 'Document'}
                          </span>
                          <span className="citation-index">{index + 1}</span>
                        </span>

                        <strong>{getCitationTitle(citation)}</strong>
                        <span className="citation-meta">
                          <span>{getCitationMeta(citation)}</span>
                          {score && <span>{score}</span>}
                        </span>

                        <blockquote>{citation.excerpt}</blockquote>
                        {isActive && (
                          <span className="focused-label">Focused evidence</span>
                        )}
                      </button>

                      {citation.type === 'literature' && citation.url && (
                        <a
                          className="source-link"
                          href={citation.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open source record
                          <ExternalLink size={13} />
                        </a>
                      )}
                      {citation.type === 'document' && citation.document_id && (
                        <>
                          {isActive && citation.page ? (
                            <DocumentPagePreview
                              documentId={citation.document_id}
                              page={citation.page}
                              title={getCitationTitle(citation)}
                            />
                          ) : null}
                          <a
                            className="source-link"
                            href={getDocumentFileUrl(
                              citation.document_id,
                              citation.page,
                            )}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {citation.page
                              ? `Open source page ${citation.page}`
                              : 'Open source file'}
                            <ExternalLink size={13} />
                          </a>
                        </>
                      )}
                    </article>
                  </li>
                )
              })}
            </ol>
          </>
        )}
      </div>
    </aside>
  )
}
