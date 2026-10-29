import { useEffect, useMemo, useState } from 'react'
import { runScenario } from '../api/client.ts'
import type { AnalysisResult } from '../api/results.ts'
import type { MobilityOptionSummary, UserProfile } from '../api/types.ts'
import { Charts } from './Charts.tsx'
import './results.css'
import {
  answerChange,
  describeActive,
  isNeutral,
  NEUTRAL_SCENARIO,
  parseScenario,
  sameScenario,
  type ScenarioKey,
  type ScenarioValues,
} from './scenario.ts'
import { ScenarioPanel } from './ScenarioPanel.tsx'
import {
  buildResultsView,
  type CardView,
  type CompositionItem,
  type Metric,
  type TodayView,
  type VerdictView,
} from './view.ts'

interface ResultsProps {
  /** The household, to analyse it again under what-if assumptions. */
  profile: UserProfile
  /** The analysis of the household as it is. */
  result: AnalysisResult
  options: MobilityOptionSummary[]
  onEdit: () => void
  onRestart: () => void
}

/** Wait this long after the last move of a slider before asking the server. */
const RECALCULATE_AFTER_MS = 300

export function Results({ profile, result, options, onEdit, onRestart }: ResultsProps) {
  // In development, /?whatif=fuelPct:30,remoteDays:2 starts with those assumptions.
  const [values, setValues] = useState<ScenarioValues>(() =>
    import.meta.env.DEV
      ? parseScenario(new URLSearchParams(window.location.search).get('whatif'))
      : NEUTRAL_SCENARIO,
  )
  // The last analysis under assumptions, with the assumptions it was made for; and the ones that failed.
  const [ready, setReady] = useState<{ values: ScenarioValues; result: AnalysisResult } | null>(null)
  const [failed, setFailed] = useState<ScenarioValues | null>(null)

  const neutral = isNeutral(values)
  const settled = ready !== null && sameScenario(ready.values, values)
  // The answer on screen is the one for the assumptions in force; while a new one is on its way the
  // previous one stays, a little faded.
  const shown = neutral ? result : (ready?.result ?? result)
  const status: 'idle' | 'loading' | 'error' =
    neutral || settled
      ? 'idle'
      : failed !== null && sameScenario(failed, values)
        ? 'error'
        : 'loading'

  // Ask for the analysis under the assumptions, after a pause. A newer move cancels the older request.
  useEffect(() => {
    if (neutral) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      const outcome = await runScenario(profile, values, controller.signal)
      if (controller.signal.aborted) return
      if (outcome.kind === 'ok') setReady({ values, result: outcome.result })
      else setFailed(values)
    }, RECALCULATE_AFTER_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [values, neutral, profile])

  const baseView = useMemo(() => buildResultsView(result, options), [result, options])
  const view = useMemo(() => buildResultsView(shown, options), [shown, options])
  const active = describeActive(values)
  const change = neutral ? null : answerChange(baseView, view)

  function change1(key: ScenarioKey, value: number) {
    setValues((current) => ({ ...current, [key]: value }))
  }

  return (
    <div className="results-layout">
      <div className={`results ${status === 'loading' ? 'is-loading' : ''}`} aria-busy={status === 'loading'}>
        <Verdict
          verdict={view.verdict}
          hasCards={view.cards.length > 0}
          assumptions={active}
          change={change}
        />
      <Today today={view.today} />

      <section id="alternative" className="block" aria-labelledby="alternative-title">
        <h2 id="alternative-title">
          {view.cards.length > 0 ? 'Le alternative che abbiamo valutato' : 'Alternative'}
        </h2>
        {view.cards.length > 0 ? (
          <>
            <p className="block-lead">
              Ognuna è confrontata con quello che hai oggi. Mostriamo le più interessanti per costo,
              tempo e comfort, e quella che ci sembra la migliore per te.
            </p>
            <div className="option-grid">
              {view.cards.map((card) => (
                <OptionCard key={card.id} card={card} />
              ))}
            </div>
          </>
        ) : (
          <p className="block-lead">
            Non abbiamo trovato alternative praticabili: con le risposte che ci hai dato, la
            configurazione di oggi è l’unica che funziona.
          </p>
        )}
      </section>

      {view.cards.length > 0 && (
        <section className="block" aria-labelledby="compare-title">
          <h2 id="compare-title">Confronto a colpo d’occhio</h2>
          <Charts charts={view.charts} table={view.table} />
        </section>
      )}

      {view.rejected.length > 0 && (
        <details className="block fold">
          <summary>
            Configurazioni che non funzionerebbero <span className="count">{view.rejected.length}</span>
          </summary>
          <p className="block-lead">
            Le abbiamo escluse prima di confrontarle, perché non riuscirebbero a coprire i vostri
            spostamenti.
          </p>
          <ul className="rejected">
            {view.rejected.map((entry) => (
              <li key={entry.id}>
                <strong>{entry.name}</strong>
                {entry.reasons.map((reason) => (
                  <span key={reason} className="reason">
                    {reason}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}

      {(view.hints.length > 0 || view.today.notes.length > 0) && (
        <section className="block precision" aria-labelledby="precision-title">
          <h2 id="precision-title">Quanto fidarsi di questi numeri</h2>
          <p className="block-lead">
            Molti dati sono stime: li abbiamo arrotondati e, dove possibile, indicato un intervallo.
          </p>
          {view.hints.length > 0 && (
            <>
              <h3>Per una stima più precisa</h3>
              <ul className="plain-list">
                {view.hints.map((hint) => (
                  <li key={hint}>{hint}</li>
                ))}
              </ul>
            </>
          )}
          {view.today.notes.length > 0 && (
            <>
              <h3>Cosa abbiamo dovuto stimare</h3>
              <ul className="plain-list">
                {view.today.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      <div className="results-actions">
        <button type="button" onClick={onEdit}>
          Modifica le risposte
        </button>
        <button type="button" className="link" onClick={onRestart}>
          Ricomincia da capo
        </button>
      </div>
      </div>

      <aside className="what-if">
        <ScenarioPanel
          values={values}
          onChange={change1}
          onReset={() => setValues(NEUTRAL_SCENARIO)}
          status={status}
          now={view}
          base={baseView}
        />
      </aside>
    </div>
  )
}

// --- the answer --------------------------------------------------------------------------------

interface VerdictProps {
  verdict: VerdictView
  hasCards: boolean
  /** The what-if assumptions in force, if any. */
  assumptions: string[]
  /** What the answer does against the one without assumptions, if it is another answer. */
  change: string | null
}

function Verdict({ verdict, hasCards, assumptions, change }: VerdictProps) {
  return (
    <section className={`verdict ${verdict.keep ? 'verdict-keep' : 'verdict-change'}`}>
      <div className="verdict-text">
        <p className="eyebrow">
          {assumptions.length > 0 ? 'La nostra risposta con le tue ipotesi' : 'La nostra risposta'}
        </p>
        <h2>{verdict.title}</h2>
        <p className="verdict-lead">{verdict.lead}</p>
        {assumptions.length > 0 && (
          <ul className="assumptions" aria-label="Ipotesi in uso">
            {assumptions.map((phrase) => (
              <li key={phrase}>{phrase}</li>
            ))}
          </ul>
        )}
        {change && <p className="answer-change">{change}</p>}
        {verdict.action && (
          <p className="verdict-action">
            <span>Cosa cambia</span> {verdict.action}
          </p>
        )}
        {hasCards && (
          <a className="button-link" href="#alternative">
            {verdict.keep ? 'Guarda le alternative' : 'Vedi come e perché'}
          </a>
        )}
      </div>
      <div className="hero">
        <p className="hero-value">{verdict.hero.value}</p>
        <p className="hero-label">{verdict.hero.label}</p>
        {verdict.hero.range && <p className="hero-range">{verdict.hero.range}</p>}
        {verdict.strength && (
          <p className={`pill pill-level-${verdict.strength.level}`}>{verdict.strength.label}</p>
        )}
      </div>
    </section>
  )
}

// --- today -----------------------------------------------------------------------------------------

function Today({ today }: { today: TodayView }) {
  return (
    <section className="today block" aria-labelledby="today-title">
      <div className="today-head">
        <h2 id="today-title">La tua situazione oggi</h2>
        <Confidence {...today.confidence} />
      </div>
      <Composition items={today.composition} empty="Nessun veicolo di proprietà né abbonamento" />
      <div className="stats">
        {today.metrics.map((metric) => (
          <Stat key={metric.label} metric={metric} />
        ))}
        <div className="stat">
          <p className="stat-label">Km in auto</p>
          <p className="stat-value stat-small">{today.carKm.replace('Km in auto: ', '')}</p>
        </div>
      </div>
    </section>
  )
}

function Stat({ metric }: { metric: Metric }) {
  return (
    <div className="stat">
      <p className="stat-label">{metric.label}</p>
      <p className="stat-value">{metric.value}</p>
      {metric.detail && <p className="stat-detail">{metric.detail}</p>}
    </div>
  )
}

function Composition({ items, empty }: { items: CompositionItem[]; empty?: string }) {
  if (items.length === 0) return empty ? <p className="muted">{empty}</p> : null
  return (
    <ul className="composition" aria-label="Mezzi e abbonamenti">
      {items.map((item) => (
        <li key={item.text}>
          <span aria-hidden="true">{item.icon}</span> {item.text}
        </li>
      ))}
    </ul>
  )
}

function Confidence({ label, level }: { label: string; level: 1 | 2 | 3 }) {
  return (
    <p className="confidence" title="Quanto sono affidabili i numeri, in base a quante risposte erano precise">
      <span className="confidence-dots" aria-hidden="true">
        {[1, 2, 3].map((n) => (
          <span key={n} className={n <= level ? 'on' : ''} />
        ))}
      </span>
      Affidabilità {label.toLowerCase()}
    </p>
  )
}

// --- an alternative -----------------------------------------------------------------------------------

function OptionCard({ card }: { card: CardView }) {
  return (
    <article className={`option ${card.isPick ? 'option-pick' : ''}`}>
      <header className="option-head">
        <div className="badges">
          {card.isPick && <span className="pill pill-pick">La nostra scelta</span>}
          {card.roles.map((role) => (
            <span key={role} className="pill pill-role">
              {role}
            </span>
          ))}
        </div>
        <span className={`pill pill-level-${card.strength.level}`}>{card.strength.label}</span>
      </header>

      <h3>{card.name}</h3>
      <p className="option-category">{card.category}</p>
      <p className="option-action">{card.action}</p>
      <Composition items={card.composition} />

      <dl className="metrics">
        {card.metrics.map((metric) => (
          <div key={metric.label} className="metric">
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
            {metric.change && <dd className={`change change-${metric.change.tone}`}>{metric.change.text}</dd>}
          </div>
        ))}
      </dl>
      <p className="muted small">{card.carKm}</p>

      {card.bottomLine && <p className="bottom-line">{card.bottomLine}</p>}
      {card.reasons.length > 0 && (
        <ul className="plain-list reasons">
          {card.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {card.moreReasons.length > 0 && (
        <details className="more">
          <summary>Altri dettagli</summary>
          <ul className="plain-list reasons">
            {card.moreReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </details>
      )}

      <footer className="option-foot">
        <Confidence {...card.confidence} />
      </footer>
    </article>
  )
}
