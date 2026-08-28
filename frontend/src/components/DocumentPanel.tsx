import { useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  FilePlus2,
  FileText,
  LoaderCircle,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import type { AsyncState, DocumentSummary } from '../types'

type DocumentPanelProps = {
  documents: DocumentSummary[]
  documentsState: AsyncState
  documentsError: string | null
  selectedDocumentIds: Set<string>
  isOpen: boolean
  onClose: () => void
  onRetry: () => void
  onToggleDocument: (documentId: string) => void
  onSelectAll: () => void
  onClearSelection: () => void
  onUpload: (file: File) => Promise<void>
  onDelete: (documentId: string) => Promise<void>
}

type ActionNotice = {
  tone: 'success' | 'error'
  message: string
} | null

type UploadJob = {
  id: string
  name: string
  status: 'queued' | 'indexing' | 'ready' | 'failed'
  message?: string
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function isPdf(file: File) {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export function DocumentPanel({
  documents,
  documentsState,
  documentsError,
  selectedDocumentIds,
  isOpen,
  onClose,
  onRetry,
  onToggleDocument,
  onSelectAll,
  onClearSelection,
  onUpload,
  onDelete,
}: DocumentPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [jobs, setJobs] = useState<UploadJob[]>([])
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [notice, setNotice] = useState<ActionNotice>(null)
  const isUploading = jobs.some(
    (job) => job.status === 'queued' || job.status === 'indexing',
  )
  const allSelected =
    documents.length > 0 && selectedDocumentIds.size === documents.length

  const updateJob = (id: string, patch: Partial<UploadJob>) => {
    setJobs((current) =>
      current.map((job) => (job.id === id ? { ...job, ...patch } : job)),
    )
  }

  const handleUpload = async (files: File[]) => {
    const pdfs = files.filter(isPdf)
    const skipped = files.length - pdfs.length
    if (pdfs.length === 0) {
      setNotice({
        tone: 'error',
        message: 'Choose PDF files. Other formats are not supported.',
      })
      return
    }

    const nextJobs: UploadJob[] = pdfs.map((file) => ({
      id: globalThis.crypto?.randomUUID?.() ?? `${file.name}-${file.size}-${Date.now()}`,
      name: file.name,
      status: 'queued',
    }))
    setJobs(nextJobs)
    setNotice(
      skipped
        ? {
            tone: 'error',
            message: `${skipped} non-PDF ${skipped === 1 ? 'file was' : 'files were'} skipped.`,
          }
        : null,
    )

    let ready = 0
    let failed = 0
    for (const [index, file] of pdfs.entries()) {
      updateJob(nextJobs[index].id, { status: 'indexing' })
      try {
        await onUpload(file)
        updateJob(nextJobs[index].id, { status: 'ready' })
        ready += 1
      } catch (error) {
        failed += 1
        updateJob(nextJobs[index].id, {
          status: 'failed',
          message:
            error instanceof Error ? error.message : 'The document could not be uploaded.',
        })
      }
    }

    setNotice({
      tone: failed > 0 && ready === 0 ? 'error' : 'success',
      message:
        failed === 0
          ? `${ready} ${ready === 1 ? 'document is' : 'documents are'} indexed and ready to query.`
          : `${ready} ready, ${failed} failed.`,
    })
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleDelete = async (document: DocumentSummary) => {
    setDeletingId(document.id)
    setNotice(null)

    try {
      await onDelete(document.id)
      setNotice({
        tone: 'success',
        message: `${document.filename} was removed from the library.`,
      })
      setConfirmDeleteId(null)
    } catch (error) {
      setNotice({
        tone: 'error',
        message:
          error instanceof Error ? error.message : 'The document could not be removed.',
      })
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <aside
      id="documents-panel"
      className={`workspace-panel document-panel ${isOpen ? 'is-open' : ''}`}
      aria-label="Document library"
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Source library</span>
          <h2>Medical documents</h2>
        </div>
        <button
          type="button"
          className="icon-button mobile-panel-close"
          onClick={onClose}
          aria-label="Close document library"
        >
          <X size={18} />
        </button>
      </div>

      <div className="upload-section">
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept=".pdf,application/pdf"
          multiple
          disabled={isUploading}
          onChange={(event) => {
            const files = [...(event.target.files ?? [])]
            if (files.length > 0) void handleUpload(files)
          }}
        />
        <div
          className={`upload-dropzone ${isDragging ? 'is-dragging' : ''} ${
            isUploading ? 'is-busy' : ''
          }`}
          role="button"
          tabIndex={isUploading ? -1 : 0}
          aria-label="Upload medical PDFs"
          aria-disabled={isUploading}
          onClick={() => {
            if (!isUploading) inputRef.current?.click()
          }}
          onKeyDown={(event) => {
            if (!isUploading && (event.key === 'Enter' || event.key === ' ')) {
              event.preventDefault()
              inputRef.current?.click()
            }
          }}
          onDragEnter={(event) => {
            event.preventDefault()
            if (!isUploading) setIsDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (event.currentTarget === event.target) setIsDragging(false)
          }}
          onDrop={(event) => {
            event.preventDefault()
            setIsDragging(false)
            const files = [...event.dataTransfer.files]
            if (files.length > 0 && !isUploading) void handleUpload(files)
          }}
        >
          <span className="upload-icon" aria-hidden="true">
            {isUploading ? (
              <LoaderCircle className="spin" size={21} />
            ) : (
              <UploadCloud size={21} />
            )}
          </span>
          <div>
            <strong>{isUploading ? 'Indexing documents…' : 'Drop medical PDFs'}</strong>
            <span>
              {isUploading
                ? 'Extracting pages one file at a time'
                : 'one or more files, or browse from your device'}
            </span>
          </div>
        </div>
        {jobs.length > 0 && (
          <ul className="upload-queue" aria-label="Upload progress">
            {jobs.map((job) => (
              <li className={`upload-job upload-job--${job.status}`} key={job.id}>
                <span>{job.name}</span>
                <small>
                  {job.status === 'queued' && 'Queued'}
                  {job.status === 'indexing' && 'Indexing'}
                  {job.status === 'ready' && 'Ready'}
                  {job.status === 'failed' && (job.message || 'Failed')}
                </small>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel-live-region" aria-live="polite">
        {notice && (
          <div className={`inline-notice inline-notice--${notice.tone}`}>
            {notice.tone === 'success' ? (
              <CheckCircle2 size={16} />
            ) : (
              <AlertCircle size={16} />
            )}
            <span>{notice.message}</span>
            <button
              type="button"
              onClick={() => setNotice(null)}
              aria-label="Dismiss notice"
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>

      <div className="library-toolbar">
        <div>
          <strong>{documents.length}</strong>{' '}
          {documents.length === 1 ? 'document' : 'documents'}
          {documents.length > 0 && (
            <span> · {selectedDocumentIds.size} active</span>
          )}
        </div>
        {documents.length > 0 && (
          <button
            type="button"
            className="text-button"
            onClick={allSelected ? onClearSelection : onSelectAll}
          >
            {allSelected ? 'Clear' : 'Select all'}
          </button>
        )}
      </div>

      <div className="document-list-wrap">
        {documentsState === 'loading' && (
          <div className="document-skeletons" aria-label="Loading documents">
            {[0, 1, 2].map((item) => (
              <div className="document-skeleton" key={item}>
                <span />
                <div>
                  <span />
                  <span />
                </div>
              </div>
            ))}
          </div>
        )}

        {documentsState === 'error' && (
          <div className="panel-state panel-state--error">
            <AlertCircle size={24} />
            <strong>Library unavailable</strong>
            <p>{documentsError}</p>
            <button type="button" className="secondary-button" onClick={onRetry}>
              <RefreshCw size={15} />
              Try again
            </button>
          </div>
        )}

        {documentsState === 'success' && documents.length === 0 && (
          <div className="panel-state">
            <span className="empty-state-icon">
              <FilePlus2 size={24} />
            </span>
            <strong>Build your source set</strong>
            <p>Upload a medical PDF to begin asking evidence-grounded questions.</p>
          </div>
        )}

        {documentsState === 'success' && documents.length > 0 && (
          <ul className="document-list">
            {documents.map((document) => {
              const isSelected = selectedDocumentIds.has(document.id)
              const isDeleting = deletingId === document.id
              const isConfirming = confirmDeleteId === document.id

              return (
                <li
                  className={`document-item ${isSelected ? 'is-selected' : ''}`}
                  key={document.id}
                >
                  <div className="document-row">
                    <label className="document-select">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleDocument(document.id)}
                        aria-label={`${isSelected ? 'Exclude' : 'Include'} ${
                          document.filename
                        }`}
                      />
                      <span className="custom-checkbox" aria-hidden="true">
                        {isSelected && <Check size={12} strokeWidth={3} />}
                      </span>
                      <span className="file-type-icon" aria-hidden="true">
                        <FileText size={17} />
                        <small>PDF</small>
                      </span>
                      <span className="document-copy">
                        <strong title={document.filename}>{document.filename}</strong>
                        <span>
                          {document.page_count} pages · {formatFileSize(document.size_bytes)}
                        </span>
                        <span className="document-chunks">
                          {document.chunk_count} indexed excerpts
                        </span>
                      </span>
                    </label>
                    <button
                      type="button"
                      className="icon-button delete-button"
                      onClick={() =>
                        setConfirmDeleteId(isConfirming ? null : document.id)
                      }
                      disabled={isDeleting}
                      aria-label={`Delete ${document.filename}`}
                      aria-expanded={isConfirming}
                    >
                      {isDeleting ? (
                        <LoaderCircle className="spin" size={16} />
                      ) : (
                        <Trash2 size={16} />
                      )}
                    </button>
                  </div>

                  {isConfirming && (
                    <div className="delete-confirm">
                      <span>Remove this source?</span>
                      <div>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="danger-button"
                          onClick={() => void handleDelete(document)}
                          disabled={isDeleting}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}
