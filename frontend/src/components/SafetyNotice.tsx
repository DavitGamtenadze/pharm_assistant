import { ShieldCheck } from 'lucide-react'

export function SafetyNotice() {
  return (
    <footer className="safety-notice" role="note" aria-label="Research use notice">
      <ShieldCheck size={16} aria-hidden="true" />
      <p>
        <strong>Research use only — not medical advice.</strong>
        <span> Verify all claims against the cited original sources.</span>
      </p>
    </footer>
  )
}
