import { useMemo, useState } from 'react'
import { type AnalyzeOutcome, analyze } from '../api/client.ts'
import type { AnalysisResult } from '../api/results.ts'
import type { UserProfile } from '../api/types.ts'
import { firstIncompleteStep, stepProblems } from '../form/rules.ts'
import { formToProfile } from '../form/mapping.ts'
import { describeForm } from '../form/summary.ts'
import type { StepId } from '../form/types.ts'
import type { StepProps } from './types.ts'

interface SummaryStepProps extends StepProps {
  onEdit: (step: StepId) => void
  onResult: (result: AnalysisResult, profile: UserProfile) => void
}

type Status = { kind: 'idle' } | { kind: 'running' } | { kind: 'done'; outcome: AnalyzeOutcome }

export function SummaryStep({ form, config, options, onEdit, onResult }: SummaryStepProps) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const incomplete = firstIncompleteStep(form)
  const sections = useMemo(() => describeForm(form, config, options), [form, config, options])
  const profile = useMemo(
    () => (incomplete === null ? formToProfile(form, config) : null),
    [incomplete, form, config],
  )

  async function run() {
    if (profile === null) return
    setStatus({ kind: 'running' })
    const outcome = await analyze(profile)
    if (outcome.kind === 'ok') onResult(outcome.result, profile)
    else setStatus({ kind: 'done', outcome })
  }

  return (
    <>
      <p className="lead">Controllate che sia tutto giusto, poi calcoliamo.</p>

      {sections.map((section) => (
        <section key={section.step} className="card">
          <div className="card-header">
            <h3>{section.title}</h3>
            <button type="button" className="link" onClick={() => onEdit(section.step)}>
              Modifica
            </button>
          </div>
          <ul className="summary-lines">
            {section.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      ))}

      {incomplete !== null && (
        <div className="notice" role="alert">
          <p>Manca ancora qualcosa:</p>
          <ul>
            {stepProblems(incomplete, form).map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
          <button type="button" className="link" onClick={() => onEdit(incomplete)}>
            Vai al passaggio da completare
          </button>
        </div>
      )}

      <button
        type="button"
        className="primary"
        disabled={profile === null || status.kind === 'running'}
        onClick={run}
      >
        {status.kind === 'running' ? 'Calcolo in corso…' : 'Calcola la mia situazione'}
      </button>

      {status.kind === 'done' && <Outcome outcome={status.outcome} />}

      {import.meta.env.DEV && profile !== null && (
        <details className="advanced">
          <summary>Profilo inviato (JSON, solo sviluppo)</summary>
          <pre>{JSON.stringify(profile, null, 2)}</pre>
        </details>
      )}
    </>
  )
}

function Outcome({ outcome }: { outcome: AnalyzeOutcome }) {
  switch (outcome.kind) {
    case 'ok':
      return null
    case 'not-ready':
      return (
        <div className="notice" role="status">
          <p>{outcome.message}</p>
          <p className="hint">
            Le tue risposte sono state controllate e accettate dal server: manca solo il calcolo.
          </p>
        </div>
      )
    case 'invalid':
      return (
        <div className="notice" role="alert">
          <p>Alcune risposte non sono valide:</p>
          <ul>
            {outcome.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )
    case 'error':
      return (
        <div className="notice" role="alert">
          {outcome.message}
        </div>
      )
  }
}
