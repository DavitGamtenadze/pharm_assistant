import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppHeader } from './components/AppHeader'
import { DocumentPanel } from './components/DocumentPanel'
import { EvidencePanel } from './components/EvidencePanel'
import { QuestionWorkspace } from './components/QuestionWorkspace'
import { SafetyNotice } from './components/SafetyNotice'
import {
  askQuestionStream,
  deleteDocument,
  getDocuments,
  getHealth,
  uploadDocument,
} from './api/client'
import type {
  AsyncState,
  ChatTurn,
  Citation,
  DocumentSummary,
  HealthStatus,
} from './types'
import './App.css'

function createTurnId() {
  return globalThis.crypto?.randomUUID?.() ?? `turn-${Date.now()}`
}

function App() {
  const initialDocumentLoad = useRef(true)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [healthState, setHealthState] = useState<AsyncState>('loading')
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [documentsState, setDocumentsState] = useState<AsyncState>('loading')
  const [documentsError, setDocumentsError] = useState<string | null>(null)
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(
    new Set(),
  )
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null)
  const [activeCitationId, setActiveCitationId] = useState<string | null>(null)
  const [includeLiterature, setIncludeLiterature] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<
    'documents' | 'evidence' | null
  >(null)

  const refreshHealth = useCallback(async () => {
    setHealthState('loading')

    try {
      const nextHealth = await getHealth()
      setHealth(nextHealth)
      setHealthState('success')
    } catch {
      setHealth(null)
      setHealthState('error')
    }
  }, [])

  const refreshDocuments = useCallback(async () => {
    setDocumentsState('loading')
    setDocumentsError(null)

    try {
      const nextDocuments = await getDocuments()
      setDocuments(nextDocuments)
      setSelectedDocumentIds((currentSelection) => {
        if (initialDocumentLoad.current) {
          return new Set(nextDocuments.map((document) => document.id))
        }

        const availableIds = new Set(nextDocuments.map((document) => document.id))
        return new Set(
          [...currentSelection].filter((documentId) =>
            availableIds.has(documentId),
          ),
        )
      })
      initialDocumentLoad.current = false
      setDocumentsState('success')
    } catch (error) {
      setDocumentsError(
        error instanceof Error ? error.message : 'The document library could not load.',
      )
      setDocumentsState('error')
    }
  }, [])

  useEffect(() => {
    let isActive = true

    void getHealth()
      .then((nextHealth) => {
        if (!isActive) return
        setHealth(nextHealth)
        setHealthState('success')
      })
      .catch(() => {
        if (!isActive) return
        setHealth(null)
        setHealthState('error')
      })

    void getDocuments()
      .then((nextDocuments) => {
        if (!isActive) return
        setDocuments(nextDocuments)
        setSelectedDocumentIds(
          new Set(nextDocuments.map((document) => document.id)),
        )
        initialDocumentLoad.current = false
        setDocumentsState('success')
      })
      .catch((error: unknown) => {
        if (!isActive) return
        setDocumentsError(
          error instanceof Error
            ? error.message
            : 'The document library could not load.',
        )
        setDocumentsState('error')
      })

    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    const closePanels = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobilePanel(null)
    }
    window.addEventListener('keydown', closePanels)
    return () => window.removeEventListener('keydown', closePanels)
  }, [])

  const handleUpload = async (file: File) => {
    const newDocument = await uploadDocument(file)
    setDocuments((currentDocuments) => [newDocument, ...currentDocuments])
    setSelectedDocumentIds((currentSelection) => {
      const nextSelection = new Set(currentSelection)
      nextSelection.add(newDocument.id)
      return nextSelection
    })
    setDocumentsState('success')
    setDocumentsError(null)
  }

  const handleDelete = async (documentId: string) => {
    await deleteDocument(documentId)
    setDocuments((currentDocuments) =>
      currentDocuments.filter((document) => document.id !== documentId),
    )
    setSelectedDocumentIds((currentSelection) => {
      const nextSelection = new Set(currentSelection)
      nextSelection.delete(documentId)
      return nextSelection
    })
  }

  const runQuestion = async (
    question: string,
    documentIds: string[],
    searchLiterature: boolean,
    retryTurnId?: string,
  ) => {
    const turnId = retryTurnId ?? createTurnId()
    const pendingTurn: ChatTurn = {
      id: turnId,
      question,
      documentIds,
      includeLiterature: searchLiterature,
      answer: '',
      citations: [],
      requestId: null,
      latencyMs: null,
      status: 'loading',
      error: null,
    }

    setTurns((currentTurns) =>
      retryTurnId
        ? currentTurns.map((turn) => (turn.id === retryTurnId ? pendingTurn : turn))
        : [...currentTurns, pendingTurn],
    )
    setActiveTurnId(turnId)
    setActiveCitationId(null)

    try {
      const response = await askQuestionStream(
        {
          question,
          document_ids: documentIds,
          top_k: 8,
          include_literature: searchLiterature,
        },
        (text) => {
          setTurns((currentTurns) =>
            currentTurns.map((turn) =>
              turn.id === turnId
                ? { ...turn, answer: `${turn.answer}${text}` }
                : turn,
            ),
          )
        },
      )

      setTurns((currentTurns) =>
        currentTurns.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                answer: response.answer,
                citations: response.citations,
                requestId: response.request_id,
                latencyMs: response.latency_ms,
                status: 'success',
              }
            : turn,
        ),
      )
      setActiveCitationId(response.citations[0]?.id ?? null)
    } catch (error) {
      setTurns((currentTurns) =>
        currentTurns.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                status: 'error',
                error:
                  error instanceof Error
                    ? error.message
                    : 'The question could not be completed.',
              }
            : turn,
        ),
      )
    }
  }

  const isAsking = turns.some((turn) => turn.status === 'loading')
  const activeTurn = useMemo(
    () =>
      turns.find((turn) => turn.id === activeTurnId) ??
      turns[turns.length - 1] ??
      null,
    [activeTurnId, turns],
  )

  const handleCitationClick = (turnId: string, citation: Citation) => {
    setActiveTurnId(turnId)
    setActiveCitationId(citation.id)
    setMobilePanel('evidence')
  }

  return (
    <div className="app-shell">
      <AppHeader
        health={health}
        healthState={healthState}
        onRetryHealth={() => void refreshHealth()}
        documentCount={documents.length}
        evidenceCount={activeTurn?.citations.length ?? 0}
        openMobilePanel={mobilePanel}
        onToggleMobilePanel={(panel) =>
          setMobilePanel((currentPanel) => (currentPanel === panel ? null : panel))
        }
      />

      <div className="workspace">
        <DocumentPanel
          documents={documents}
          documentsState={documentsState}
          documentsError={documentsError}
          selectedDocumentIds={selectedDocumentIds}
          isOpen={mobilePanel === 'documents'}
          onClose={() => setMobilePanel(null)}
          onRetry={() => void refreshDocuments()}
          onToggleDocument={(documentId) =>
            setSelectedDocumentIds((currentSelection) => {
              const nextSelection = new Set(currentSelection)
              if (nextSelection.has(documentId)) nextSelection.delete(documentId)
              else nextSelection.add(documentId)
              return nextSelection
            })
          }
          onSelectAll={() =>
            setSelectedDocumentIds(
              new Set(documents.map((document) => document.id)),
            )
          }
          onClearSelection={() => setSelectedDocumentIds(new Set())}
          onUpload={handleUpload}
          onDelete={handleDelete}
        />

        <QuestionWorkspace
          turns={turns}
          selectedDocumentCount={selectedDocumentIds.size}
          documentFilenames={documents.map((document) => document.filename)}
          includeLiterature={includeLiterature}
          isAsking={isAsking}
          onIncludeLiteratureChange={setIncludeLiterature}
          onAsk={(question) =>
            void runQuestion(
              question,
              [...selectedDocumentIds],
              includeLiterature,
            )
          }
          onRetry={(turn) =>
            void runQuestion(
              turn.question,
              turn.documentIds,
              turn.includeLiterature,
              turn.id,
            )
          }
          onClearThread={() => {
            setTurns([])
            setActiveTurnId(null)
            setActiveCitationId(null)
          }}
          onCitationClick={handleCitationClick}
        />

        <EvidencePanel
          activeTurn={activeTurn}
          activeCitationId={activeCitationId}
          isOpen={mobilePanel === 'evidence'}
          onClose={() => setMobilePanel(null)}
          onSelectCitation={setActiveCitationId}
        />
      </div>

      {mobilePanel && (
        <button
          type="button"
          className="panel-backdrop"
          onClick={() => setMobilePanel(null)}
          aria-label="Close workspace panel"
        />
      )}

      <SafetyNotice />
    </div>
  )
}

export default App
