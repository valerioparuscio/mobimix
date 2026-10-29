import {
  CONTROLS,
  type ControlDef,
  isNeutral,
  type ScenarioKey,
  type ScenarioValues,
} from './scenario.ts'
import type { ResultsView } from './view.ts'

interface ScenarioPanelProps {
  values: ScenarioValues
  onChange: (key: ScenarioKey, value: number) => void
  onReset: () => void
  status: 'idle' | 'loading' | 'error'
  /** The answer as it is now, and as it was without the assumptions. */
  now: ResultsView
  base: ResultsView
}

/** "E se…?": a few assumptions the household can change, and the answer that follows. */
export function ScenarioPanel({ values, onChange, onReset, status, now, base }: ScenarioPanelProps) {
  const neutral = isNeutral(values)
  return (
    <section className="what-if-panel" aria-labelledby="what-if-title">
      <h2 id="what-if-title">E se…?</h2>
      <p className="what-if-lead">
        Cambia un’ipotesi e guarda cosa succede. I risultati si aggiornano da soli.
      </p>

      {CONTROLS.map((control) => (
        <Slider
          key={control.key}
          control={control}
          value={values[control.key]}
          onChange={(value) => onChange(control.key, value)}
        />
      ))}

      <div className="what-if-foot">
        <button type="button" onClick={onReset} disabled={neutral}>
          Torna ai valori di partenza
        </button>
        <p className="what-if-status" role="status" aria-live="polite">
          {status === 'loading' && 'Ricalcolo…'}
          {status === 'error' && 'Non riusciamo a ricalcolare. Riprova tra poco.'}
        </p>
      </div>

      <div className="what-if-summary">
        <p className="what-if-summary-label">In sintesi</p>
        <p className="what-if-summary-title">{now.verdict.title}</p>
        <p className="what-if-summary-figure">
          <strong>{now.verdict.hero.value}</strong> {now.verdict.hero.label}
        </p>
        {!neutral && (
          <p className="what-if-summary-before">
            Senza ipotesi: {base.verdict.title.replace(/\.$/, '')} ({base.verdict.hero.value}{' '}
            {base.verdict.hero.label})
          </p>
        )}
      </div>
    </section>
  )
}

function Slider({
  control,
  value,
  onChange,
}: {
  control: ControlDef
  value: number
  onChange: (value: number) => void
}) {
  const id = `what-if-${control.key}`
  const changed = control.phrase(value) !== null
  return (
    <div className="what-if-control">
      <div className="what-if-row">
        <label htmlFor={id}>{control.label}</label>
        <output htmlFor={id} className={changed ? 'what-if-value changed' : 'what-if-value'}>
          {control.show(value)}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={control.min}
        max={control.max}
        step={control.step}
        value={value}
        aria-valuetext={control.show(value)}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <div className="what-if-ends" aria-hidden="true">
        <span>{control.ends[0]}</span>
        <span>{control.ends[1]}</span>
      </div>
      <p className="what-if-hint">{control.hint}</p>
    </div>
  )
}
