import { Field } from '../components/controls.tsx'
import { AREA_DESCRIPTIONS, AREA_LABELS, AREA_ORDER } from '../form/labels.ts'
import type { StepProps } from './types.ts'

export function LocationStep({ form, setForm }: StepProps) {
  return (
    <>
      <p className="lead">
        Il luogo in cui abitate cambia molto cosa è realistico: trasporto pubblico, parcheggio,
        servizi di sharing.
      </p>
      <Field label="In che comune abitate?" hint="Facoltativo. Non chiediamo l’indirizzo.">
        <input
          type="text"
          className="text-input"
          autoComplete="off"
          value={form.municipality}
          onChange={(event) => {
            const municipality = event.target.value
            setForm((current) => ({ ...current, municipality }))
          }}
        />
      </Field>
      <fieldset className="cards">
        <legend className="field-label">Come descrivereste la zona in cui abitate?</legend>
        {AREA_ORDER.map((area) => (
          <label key={area} className="choice-card">
            <input
              type="radio"
              name="area-type"
              checked={form.areaType === area}
              onChange={() => setForm((current) => ({ ...current, areaType: area }))}
            />
            <span>
              <strong>{AREA_LABELS[area]}</strong>
              <span className="hint">{AREA_DESCRIPTIONS[area]}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </>
  )
}
