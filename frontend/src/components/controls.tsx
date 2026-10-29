import type { ReactNode } from 'react'
import type { BandGroup } from '../api/types.ts'
import type { NumericForm } from '../form/types.ts'

// --- Chips: a single-choice group rendered as buttons ------------------------------------

export interface ChipOption<T extends string> {
  value: T
  label: string
}

interface ChipsProps<T extends string> {
  label: string
  options: ChipOption<T>[]
  value: T | null
  onChange: (value: T) => void
}

export function Chips<T extends string>({ label, options, value, onChange }: ChipsProps<T>) {
  return (
    <div className="chips" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className="chip"
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

// --- Stepper: small whole numbers (adults, cars, days) ----------------------------------

interface StepperProps {
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}

export function Stepper({ label, value, min, max, onChange }: StepperProps) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button
        type="button"
        aria-label={`Meno: ${label}`}
        disabled={value <= min}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <output aria-live="polite">{value}</output>
      <button
        type="button"
        aria-label={`Più: ${label}`}
        disabled={value >= max}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </div>
  )
}

// --- Field: label + optional hint around a control --------------------------------------

interface FieldProps {
  label: string
  hint?: string
  children: ReactNode
}

export function Field({ label, hint, children }: FieldProps) {
  return (
    <div className="field">
      <div className="field-label">{label}</div>
      {hint && <p className="hint">{hint}</p>}
      {children}
    </div>
  )
}

// --- NumericField: exact value, band, or "I don't know" ---------------------------------

interface NumericFieldProps {
  label: string
  hint?: string
  group: BandGroup
  value: NumericForm
  onChange: (value: NumericForm) => void
}

/**
 * A number the user may not know (brief section 4): pick a band, type an exact value, or say
 * "Non so" and let the model estimate it. Bands come from data/questionnaire.yaml.
 */
export function NumericField({ label, hint, group, value, onChange }: NumericFieldProps) {
  const selected =
    value.kind === 'band'
      ? `band:${value.bandId}`
      : value.kind === 'exact'
        ? 'exact'
        : value.kind === 'range'
          ? 'range'
          : 'unknown'

  const choices: ChipOption<string>[] = [
    ...group.bands.map((band) => ({ value: `band:${band.id}`, label: band.label })),
    ...(value.kind === 'range'
      ? [{ value: 'range', label: `Circa ${value.low} – ${value.high}` }]
      : []),
    { value: 'exact', label: 'Valore preciso' },
    { value: 'unknown', label: 'Non so' },
  ]

  function choose(choice: string) {
    if (choice === 'unknown') onChange({ kind: 'unknown' })
    else if (choice === 'exact') onChange({ kind: 'exact', value: value.kind === 'exact' ? value.value : null })
    else if (choice.startsWith('band:')) onChange({ kind: 'band', bandId: choice.slice(5) })
    // 'range' is the already-selected custom range: nothing to change
  }

  return (
    <Field label={label} hint={hint}>
      <Chips label={label} options={choices} value={selected} onChange={choose} />
      {value.kind === 'exact' && (
        <label className="exact-input">
          <span className="visually-hidden">{label}: valore preciso</span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            value={value.value ?? ''}
            placeholder={group.unit ?? ''}
            onChange={(event) =>
              onChange({
                kind: 'exact',
                value: event.target.value === '' ? null : Number(event.target.value),
              })
            }
          />
          {group.unit && <span className="unit">{group.unit}</span>}
        </label>
      )}
      {value.kind === 'unknown' && (
        <p className="hint">Se non lo sai, lo stimiamo noi da dati statistici.</p>
      )}
    </Field>
  )
}
