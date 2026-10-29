import type { Preferences } from '../api/types.ts'
import type { StepProps } from './types.ts'

interface SliderProps {
  label: string
  value: number
  onChange: (value: number) => void
}

function Slider({ label, value, onChange }: SliderProps) {
  return (
    <label className="slider">
      <span className="field-label">{label}</span>
      <input
        type="range"
        min={0}
        max={5}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="slider-scale" aria-hidden="true">
        <span>per niente</span>
        <span>{value}/5</span>
        <span>molto</span>
      </span>
    </label>
  )
}

export function PreferencesStep({ form, setForm }: StepProps) {
  const set = (key: keyof Preferences) => (value: number) =>
    setForm((current) => ({ ...current, preferences: { ...current.preferences, [key]: value } }))

  return (
    <>
      <p className="lead">
        Non c’è una risposta giusta. Se lasciate tutto com’è, trattiamo le quattro cose allo stesso
        modo.
      </p>
      <Slider label="Risparmiare" value={form.preferences.save_money} onChange={set('save_money')} />
      <Slider
        label="Metterci meno tempo"
        value={form.preferences.reduce_travel_time}
        onChange={set('reduce_travel_time')}
      />
      <Slider
        label="Viaggiare comodi"
        value={form.preferences.comfort}
        onChange={set('comfort')}
      />
      <Slider
        label="Poter partire quando serve (flessibilità)"
        value={form.preferences.flexibility}
        onChange={set('flexibility')}
      />

      <details className="advanced">
        <summary>Altre preferenze (facoltative)</summary>
        <p className="hint">
          Sono spente di default: MobiMix non favorisce nessun mezzo a meno che non lo chiediate voi.
        </p>
        <Slider
          label="Dipendere meno dall’auto"
          value={form.preferences.reduce_car_dependence}
          onChange={set('reduce_car_dependence')}
        />
        <Slider
          label="Ridurre l’impatto ambientale"
          value={form.preferences.sustainability}
          onChange={set('sustainability')}
        />
      </details>
    </>
  )
}
