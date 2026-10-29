import { useEffect, useState } from 'react'
import { getMobilityOptions, getQuestionnaire } from './api/client.ts'
import type { MobilityOptionSummary, QuestionnaireConfig } from './api/types.ts'
import { Wizard } from './Wizard.tsx'

interface ReferenceData {
  config: QuestionnaireConfig
  options: MobilityOptionSummary[]
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: ReferenceData }
  | { kind: 'failed'; reason: string }

// Loads the reference data the questionnaire is built from (answer bands, option catalogue),
// then shows the wizard. Routing, landing page and results pages come in later steps.
export default function App() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    Promise.all([getQuestionnaire(), getMobilityOptions()])
      .then(([config, options]) => setState({ kind: 'ready', data: { config, options } }))
      .catch((error: unknown) =>
        setState({
          kind: 'failed',
          reason: error instanceof Error ? error.message : String(error),
        }),
      )
  }, [])

  return (
    <main>
      <header className="site-header">
        <h1 className="brand">
          <span className="brand-mark" aria-hidden="true" />
          MobiMix
        </h1>
        <p className="tagline">Quali mezzi ti servono davvero? Scoprilo in pochi minuti.</p>
      </header>
      {state.kind === 'loading' && <p>Caricamento in corso…</p>}
      {state.kind === 'failed' && (
        <div className="notice" role="alert">
          <p>Non riusciamo a raggiungere il server.</p>
          <p className="hint">Dettaglio: {state.reason}</p>
        </div>
      )}
      {state.kind === 'ready' && (
        <Wizard config={state.data.config} options={state.data.options} />
      )}
    </main>
  )
}
