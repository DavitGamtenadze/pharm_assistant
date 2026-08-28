import {
  ArrowUp,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  FileText,
  LoaderCircle,
  RotateCcw,
  Search,
  Sparkles,
  UserRound,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChatTurn, Citation } from '../types'

type QuestionWorkspaceProps = {
  turns: ChatTurn[]
  selectedDocumentCount: number
  documentFilenames: string[]
  includeLiterature: boolean
  isAsking: boolean
  onIncludeLiteratureChange: (value: boolean) => void
  onAsk: (question: string) => void
  onRetry: (turn: ChatTurn) => void
  onClearThread: () => void
  onCitationClick: (turnId: string, citation: Citation) => void
}

const GENERIC_STARTERS = [
  'Summarize the study design and primary endpoints.',
  'What safety outcomes and adverse events were reported?',
  'Compare the key inclusion and exclusion criteria.',
]

const TARGET_PDF_STARTERS = [
  'What makes a medication high-risk or high-alert according to the document?',
  'What does LASA stand for, and why does it matter for medication safety?',
  'What should a Manual of Operations and Procedures (MOP) contain and how is it maintained?',
]

function starterQuestions(filenames: string[]) {
  const names = filenames.join(' ').toLowerCase()
  if (
    names.includes('who_medication') ||
    names.includes('high_risk') ||
    names.includes('nih_manual') ||
    names.includes('mop')
  ) {
    return TARGET_PDF_STARTERS
  }
  return GENERIC_STARTERS
}

function formatLatency(latencyMs: number | null) {
  if (latencyMs === null) return ''
  if (latencyMs < 1000) return `${latencyMs} ms`
  return `${(latencyMs / 1000).toFixed(1)} s`
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function AnswerCopy({
  turn,
  onCitationClick,
}: {
  turn: ChatTurn
  onCitationClick: (turnId: string, citation: Citation) => void
}) {
  if (turn.citations.length === 0) {
    return <div className="answer-copy">{turn.answer}</div>
  }

  const byLabel = new Map(turn.citations.map((citation) => [citation.label, citation]))
  const matcher = new RegExp(
    `(${[...byLabel.keys()].map(escapeRegExp).join('|')})`,
    'g',
  )

  return (
    <div className="answer-copy">
      {turn.answer.split(matcher).map((part, index) => {
        const citation = byLabel.get(part)
        if (!citation) return part
        const compactLabel =
          citation.type === 'literature'
            ? `[${citation.external_id ?? 'external'}]`
            : `[p.${citation.page ?? 'source'}]`
        return (
          <button
            type="button"
            className={`inline-citation inline-citation--${citation.type}`}
            key={`${citation.id}-${index}`}
            onClick={() => onCitationClick(turn.id, citation)}
            title={`Inspect ${citation.label}`}
          >
            {compactLabel}
          </button>
        )
      })}
    </div>
  )
}

export function QuestionWorkspace({
  turns,
  selectedDocumentCount,
  includeLiterature,
  isAsking,
  onIncludeLiteratureChange,
  onAsk,
  onRetry,
  onClearThread,
  onCitationClick,
  documentFilenames,
}: QuestionWorkspaceProps) {
  const [question, setQuestion] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const threadEndRef = useRef<HTMLDivElement>(null)
  const canAsk =
    question.trim().length > 0 &&
    !isAsking &&
    (selectedDocumentCount > 0 || includeLiterature)

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  const submitQuestion = () => {
    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || !canAsk) return
    onAsk(trimmedQuestion)
    setQuestion('')
    if (textareaRef.current) textareaRef.current.style.height = ''
  }

  return (
    <main className="question-workspace">
      <div className="thread-header">
        <div>
          <span className="eyebrow">Evidence Q&amp;A</span>
          <h1>Research thread</h1>
        </div>
        {turns.length > 0 && (
          <button
            className="text-button clear-thread-button"
            type="button"
            onClick={onClearThread}
            disabled={isAsking}
          >
            <RotateCcw size={14} />
            New thread
          </button>
        )}
      </div>

      <div className="thread-scroll" aria-live="polite">
        {turns.length === 0 ? (
          <section className="thread-empty" aria-labelledby="welcome-heading">
            <div className="assistant-orb" aria-hidden="true">
              <Sparkles size={24} />
            </div>
            <span className="welcome-kicker">Grounded in your sources</span>
            <h2 id="welcome-heading">Explore medical evidence with confidence</h2>
            <p>
              Ask focused questions across the files you selected, then check the
              exact excerpts behind the answer.
            </p>

            <div className="capability-row" aria-label="Assistant capabilities">
              <span>
                <FileText size={14} /> Page citations
              </span>
              <span>
                <Search size={14} /> External literature
              </span>
              <span>
                <CheckCircle2 size={14} /> Source-grounded
              </span>
            </div>

            <div className="starter-questions">
              <span className="starter-label">Try asking</span>
              {starterQuestions(documentFilenames).map((starter) => (
                <button
                  key={starter}
                  type="button"
                  onClick={() => onAsk(starter)}
                >
                  <span>{starter}</span>
                  <ArrowUp size={15} aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        ) : (
          <div className="turn-list">
            {turns.map((turn) => (
              <article className="conversation-turn" key={turn.id}>
                <div className="user-message">
                  <div className="message-avatar message-avatar--user" aria-hidden="true">
                    <UserRound size={15} />
                  </div>
                  <div>
                    <span className="message-author">You</span>
                    <p>{turn.question}</p>
                    <span className="question-context">
                      {turn.documentIds.length}{' '}
                      {turn.documentIds.length === 1 ? 'document' : 'documents'}
                      {turn.includeLiterature && ' + external literature'}
                    </span>
                  </div>
                </div>

                <div className={`assistant-message assistant-message--${turn.status}`}>
                  <div
                    className="message-avatar message-avatar--assistant"
                    aria-hidden="true"
                  >
                    <Sparkles size={15} />
                  </div>
                  <div className="assistant-message-body">
                    <span className="message-author">Medical Document Assistant</span>

                    {turn.status === 'loading' && (
                      <div className="answer-loading" role="status">
                        <div className="thinking-label">
                          <LoaderCircle className="spin" size={15} />
                          {turn.answer
                            ? 'Writing grounded answer…'
                            : 'Reviewing selected evidence…'}
                        </div>
                        {turn.answer ? (
                          <div className="answer-copy answer-copy--streaming">
                            {turn.answer}
                          </div>
                        ) : (
                          <>
                            <span />
                            <span />
                            <span />
                          </>
                        )}
                      </div>
                    )}

                    {turn.status === 'error' && (
                      <div className="answer-error" role="alert">
                        <CircleAlert size={18} />
                        <div>
                          <strong>Unable to complete this question</strong>
                          <p>{turn.error}</p>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => onRetry(turn)}
                            disabled={isAsking}
                          >
                            <RotateCcw size={14} />
                            Try again
                          </button>
                        </div>
                      </div>
                    )}

                    {turn.status === 'success' && (
                      <>
                        <AnswerCopy turn={turn} onCitationClick={onCitationClick} />

                        {turn.citations.length > 0 ? (
                          <div
                            className="citation-chip-list"
                            aria-label="Answer citations"
                          >
                            {turn.citations.map((citation, index) => (
                              <button
                                type="button"
                                className={`citation-chip citation-chip--${citation.type}`}
                                key={citation.id}
                                onClick={() => onCitationClick(turn.id, citation)}
                                aria-label={`Focus citation ${index + 1}: ${citation.label}`}
                              >
                                {citation.type === 'literature' ? (
                                  <BookOpen size={13} />
                                ) : (
                                  <FileText size={13} />
                                )}
                                <span>{index + 1}</span>
                                <small>
                                  {citation.type === 'literature'
                                    ? citation.source || 'Literature'
                                    : citation.page
                                      ? `p. ${citation.page}`
                                      : 'source'}
                                </small>
                              </button>
                            ))}
                          </div>
                        ) : (
                          <div className="no-citations-note">
                            <CircleAlert size={14} />
                            No source excerpts were returned for this answer.
                          </div>
                        )}

                        <div className="answer-meta">
                          <span>
                            {turn.citations.length}{' '}
                            {turn.citations.length === 1 ? 'source' : 'sources'}
                          </span>
                          {turn.latencyMs !== null && (
                            <>
                              <span aria-hidden="true">·</span>
                              <span>{formatLatency(turn.latencyMs)}</span>
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        <div ref={threadEndRef} />
      </div>

      <div className="composer-area">
        <div className="composer">
          <label className="visually-hidden" htmlFor="research-question">
            Ask a question about your medical sources
          </label>
          <textarea
            ref={textareaRef}
            id="research-question"
            rows={1}
            value={question}
            placeholder="Ask a question about the selected evidence…"
            onChange={(event) => setQuestion(event.target.value)}
            onInput={(event) => {
              const textarea = event.currentTarget
              textarea.style.height = 'auto'
              textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submitQuestion()
              }
            }}
          />

          <div className="composer-toolbar">
            <button
              type="button"
              role="switch"
              aria-checked={includeLiterature}
              aria-label="Search external literature with Europe PMC"
              className={`literature-toggle ${
                includeLiterature ? 'is-enabled' : ''
              }`}
              onClick={() => onIncludeLiteratureChange(!includeLiterature)}
            >
              <span className="toggle-control" aria-hidden="true">
                <span />
              </span>
              <Search size={14} />
              <span>Search literature</span>
            </button>

            <div className="composer-actions">
              <span className="source-count">
                {selectedDocumentCount > 0
                  ? `${selectedDocumentCount} ${
                      selectedDocumentCount === 1 ? 'source' : 'sources'
                    } selected`
                  : includeLiterature
                    ? 'External literature only'
                    : 'No sources selected'}
              </span>
              <button
                type="button"
                className="send-button"
                onClick={submitQuestion}
                disabled={!canAsk}
                aria-label={isAsking ? 'Answer in progress' : 'Ask question'}
              >
                {isAsking ? (
                  <LoaderCircle className="spin" size={18} />
                ) : (
                  <ArrowUp size={18} strokeWidth={2.4} />
                )}
              </button>
            </div>
          </div>
        </div>

        {selectedDocumentCount === 0 && !includeLiterature && (
          <p className="composer-guidance">
            Select at least one document or enable external literature to ask a
            grounded question.
          </p>
        )}
      </div>
    </main>
  )
}
