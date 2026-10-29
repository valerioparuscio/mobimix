import { useState } from 'react'
import type { ChartView, TableRow } from './view.ts'

interface ChartsProps {
  charts: ChartView[]
  table: TableRow[]
}

/** The three comparisons side by side, with the same numbers as a table one click away. */
export function Charts({ charts, table }: ChartsProps) {
  const [mode, setMode] = useState<'charts' | 'table'>('charts')
  return (
    <div className="compare">
      <div className="compare-bar">
        <div className="segmented" role="group" aria-label="Come vuoi vedere il confronto">
          <button type="button" aria-pressed={mode === 'charts'} onClick={() => setMode('charts')}>
            Grafici
          </button>
          <button type="button" aria-pressed={mode === 'table'} onClick={() => setMode('table')}>
            Tabella
          </button>
        </div>
        {mode === 'charts' && <Legend />}
      </div>

      {mode === 'charts' ? (
        <div className="chart-grid">
          {charts.map((chart) => (
            <BarChart key={chart.id} chart={chart} />
          ))}
        </div>
      ) : (
        <ComparisonTable rows={table} />
      )}
    </div>
  )
}

function Legend() {
  return (
    <ul className="legend" aria-label="Legenda">
      <li>
        <span className="key key-today" aria-hidden="true" /> Oggi
      </li>
      <li>
        <span className="key key-option" aria-hidden="true" /> Alternative
      </li>
      <li>
        <span className="key key-pick" aria-hidden="true" /> La nostra scelta
      </li>
    </ul>
  )
}

function BarChart({ chart }: { chart: ChartView }) {
  return (
    <figure className="chart">
      <figcaption>
        <strong>{chart.title}</strong>
        <span>{chart.caption}</span>
      </figcaption>
      <ul className="bars">
        {chart.rows.map((row) => (
          <li key={row.id} className="bar-row" tabIndex={0} aria-label={row.title}>
            <span className="bar-label">{row.label}</span>
            <span className="bar-track">
              <span
                className={`bar bar-${row.tone}`}
                style={{ '--share': Math.max(row.value / chart.max, 0.02) } as React.CSSProperties}
              />
              <span className="bar-value">{row.display}</span>
            </span>
            <span className="tip" role="tooltip">
              {row.title}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  )
}

function ComparisonTable({ rows }: { rows: TableRow[] }) {
  return (
    <div className="table-wrap">
      <table className="compare-table">
        <caption className="visually-hidden">Confronto tra la situazione di oggi e le alternative</caption>
        <thead>
          <tr>
            <th scope="col">Configurazione</th>
            <th scope="col">Costo l’anno</th>
            <th scope="col">Tempo in viaggio</th>
            <th scope="col">Comfort (su 10)</th>
            <th scope="col">Km in auto</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th scope="row">
                <span className="row-label">{row.label}</span>
                <span className="row-name">{row.name}</span>
              </th>
              <td>{row.cost}</td>
              <td>{row.hours}</td>
              <td>{row.comfort}</td>
              <td>{row.carKm}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
