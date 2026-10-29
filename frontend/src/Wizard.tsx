import { useEffect, useRef, useState } from 'react'
import { analyze, getDemoHouseholds } from './api/client.ts'
import type { AnalysisResult } from './api/results.ts'
import type { MobilityOptionSummary, QuestionnaireConfig, UserProfile } from './api/types.ts'
import { emptyForm } from './form/defaults.ts'
import { profileToForm } from './form/mapping.ts'
import { STEP_ORDER, STEP_TITLES, stepProblems } from './form/rules.ts'
import { clearDraft, loadDraft, saveDraft } from './form/storage.ts'
import type { FormState, StepId } from './form/types.ts'
import { Results } from './results/Results.tsx'
import { CarsStep } from './steps/CarsStep.tsx'
import { HouseholdStep } from './steps/HouseholdStep.tsx'
import { LocationStep } from './steps/LocationStep.tsx'
import { MobilityStep } from './steps/MobilityStep.tsx'
import { OccasionalStep } from './steps/OccasionalStep.tsx'
import { PreferencesStep } from './steps/PreferencesStep.tsx'
import { SummaryStep } from './steps/SummaryStep.tsx'
import type { StepProps } from './steps/types.ts'
import { WorkStep } from './steps/WorkStep.tsx'

interface WizardProps {
  config: QuestionnaireConfig
  options: MobilityOptionSummary[]
}

function isStepId(value: unknown): value is StepId {
  return typeof value === 'string' && (STEP_ORDER as readonly string[]).includes(value)
}

export function Wizard({ config, options }: WizardProps) {
  // The draft is read once, on first render, and kept up to date afterwards.
  const [initial] = useState(loadDraft)
  const [form, setFormState] = useState<FormState>(initial?.form ?? emptyForm())
  const [step, setStep] = useState<StepId>(isStepId(initial?.step) ? initial.step : 'household')
  // The analysis on screen, and the household it was made for (to rerun it under what-if assumptions).
  const [run, setRun] = useState<{ profile: UserProfile; result: AnalysisResult } | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => saveDraft({ version: 1, step, form }), [step, form])
  useEffect(() => {
    window.scrollTo(0, 0)
    heading.current?.focus()
  }, [step])

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [run])
  // Development shortcut: /?demo=urban_single loads that household and goes straight to the results.
  useEffect(() => {
    if (!import.meta.env.DEV) return
    const name = new URLSearchParams(window.location.search).get('demo')
    if (!name) return
    getDemoHouseholds()
      .then(async (households) => {
        const profile = households[name]
        if (!profile) return
        setFormState(profileToForm(profile, config, options))
        const outcome = await analyze(profile)
        if (outcome.kind === 'ok') setRun({ profile, result: outcome.result })
      })
      .catch(() => undefined)
  }, [config, options])

  const index = STEP_ORDER.indexOf(step)
  const problems = stepProblems(step, form)
  const props: StepProps = { form, setForm: setFormState, config, options }

  function restart() {
    if (!window.confirm('Vuoi cancellare le risposte e ricominciare?')) return
    clearDraft()
    setFormState(emptyForm())
    setStep('household')
    setRun(null)
  }

  function loadExample(profile: UserProfile) {
    setFormState(profileToForm(profile, config, options))
    setStep('summary')
  }

  if (run !== null) {
    return (
      <Results
        profile={run.profile}
        result={run.result}
        options={options}
        onEdit={() => {
          setRun(null)
          setStep('summary')
        }}
        onRestart={restart}
      />
    )
  }

  return (
    <div className="wizard">
      <div className="wizard-bar">
        <p className="progress-label">
          Passo {index + 1} di {STEP_ORDER.length}
        </p>
        <div className="wizard-actions">
          {import.meta.env.DEV && <DemoLoader onLoad={loadExample} />}
          <button type="button" className="link" onClick={restart}>
            Ricomincia
          </button>
        </div>
      </div>
      <progress value={index + 1} max={STEP_ORDER.length} aria-label="Avanzamento" />

      <h2 ref={heading} tabIndex={-1}>
        {STEP_TITLES[step]}
      </h2>

      {step === 'household' && <HouseholdStep {...props} />}
      {step === 'location' && <LocationStep {...props} />}
      {step === 'work' && <WorkStep {...props} />}
      {step === 'cars' && <CarsStep {...props} />}
      {step === 'mobility' && <MobilityStep {...props} />}
      {step === 'occasional' && <OccasionalStep {...props} />}
      {step === 'preferences' && <PreferencesStep {...props} />}
      {step === 'summary' && <SummaryStep {...props} onEdit={setStep} onResult={(result, profile) => setRun({ profile, result })} />}

      {step !== 'summary' && (
        <nav className="wizard-nav" aria-label="Navigazione">
          {problems.length > 0 && (
            <ul className="problems" role="status">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
          <div className="nav-buttons">
            <button
              type="button"
              disabled={index === 0}
              onClick={() => setStep(STEP_ORDER[index - 1]!)}
            >
              Indietro
            </button>
            <button
              type="button"
              className="primary"
              disabled={problems.length > 0}
              onClick={() => setStep(STEP_ORDER[index + 1]!)}
            >
              Avanti
            </button>
          </div>
        </nav>
      )}
      {step === 'summary' && (
        <nav className="wizard-nav" aria-label="Navigazione">
          <div className="nav-buttons">
            <button type="button" onClick={() => setStep(STEP_ORDER[index - 1]!)}>
              Indietro
            </button>
          </div>
        </nav>
      )}
    </div>
  )
}

/** Development helper: fills the form with one of the demo households. */
function DemoLoader({ onLoad }: { onLoad: (profile: UserProfile) => void }) {
  const [households, setHouseholds] = useState<Record<string, UserProfile>>({})

  useEffect(() => {
    getDemoHouseholds()
      .then(setHouseholds)
      .catch(() => setHouseholds({}))
  }, [])

  const names = Object.keys(households)
  if (names.length === 0) return null
  return (
    <select
      aria-label="Carica un esempio"
      value=""
      onChange={(event) => {
        const profile = households[event.target.value]
        if (profile) onLoad(profile)
      }}
    >
      <option value="">Carica un esempio…</option>
      {names.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  )
}
