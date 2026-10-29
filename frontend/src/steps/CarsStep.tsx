import { Chips, Field, NumericField, Stepper } from '../components/controls.tsx'
import { MAX_CARS, setCarCount, updateCar } from '../form/actions.ts'
import { FREQUENCY_LABELS, FREQUENCY_ORDER } from '../form/labels.ts'
import { showCarDetails, showSimultaneity } from '../form/rules.ts'
import { BAND_GROUPS, CAR_OPTION_IDS } from '../form/types.ts'
import { optionsWithIds } from './types.ts'
import type { StepProps } from './types.ts'

export function CarsStep({ form, setForm, config, options }: StepProps) {
  const carTypes = optionsWithIds(options, CAR_OPTION_IDS).map((option) => ({
    value: option.id,
    label: option.name,
  }))
  const kmGroup = config.groups[BAND_GROUPS.annualKm]
  const parkingGroup = config.groups[BAND_GROUPS.parkingCostYear]

  return (
    <>
      <p className="lead">
        L’auto è di solito la voce più pesante: tipo, chilometri e parcheggio fanno la differenza.
      </p>
      <Field label="Quante auto possedete?">
        <Stepper
          label="auto"
          value={form.cars.length}
          min={0}
          max={MAX_CARS}
          onChange={(count) => setForm((current) => setCarCount(current, count))}
        />
      </Field>

      {showCarDetails(form) &&
        form.cars.map((car, index) => {
          const patch = (changes: Parameters<typeof updateCar>[2]) =>
            setForm((current) => updateCar(current, car.id, changes))
          return (
            <section key={car.id} className="card">
              <h3>Auto {index + 1}</h3>
              <Field label="Che tipo di auto è?">
                <Chips
                  label={`Tipo di auto ${index + 1}`}
                  options={carTypes}
                  value={car.optionId}
                  onChange={(optionId) => patch({ optionId })}
                />
              </Field>
              {kmGroup && (
                <NumericField
                  label="Quanti chilometri fa in un anno?"
                  group={kmGroup}
                  value={car.annualKm}
                  onChange={(annualKm) => patch({ annualKm })}
                />
              )}
              {parkingGroup && (
                <NumericField
                  label="Quanto spendete in un anno per parcheggio, box o permesso?"
                  group={parkingGroup}
                  value={car.parkingCostYear}
                  onChange={(parkingCostYear) => patch({ parkingCostYear })}
                />
              )}
            </section>
          )
        })}

      {showSimultaneity(form) && (
        <Field
          label="Quanto spesso due auto servono nello stesso momento?"
          hint="Per esempio quando due persone devono muoversi in orari uguali verso posti diversi."
        >
          <Chips
            label="Frequenza di bisogno simultaneo"
            options={FREQUENCY_ORDER.map((value) => ({ value, label: FREQUENCY_LABELS[value] }))}
            value={form.simultaneousCarNeed}
            onChange={(simultaneousCarNeed) =>
              setForm((current) => ({ ...current, simultaneousCarNeed }))
            }
          />
        </Field>
      )}
    </>
  )
}
