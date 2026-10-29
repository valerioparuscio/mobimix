import { Field, Stepper } from '../components/controls.tsx'
import {
  MAX_PER_OTHER_VEHICLE,
  countOtherVehicles,
  setOtherVehicleCount,
  updateAdult,
} from '../form/actions.ts'
import { OTHER_VEHICLE_OPTION_IDS } from '../form/types.ts'
import { optionsWithIds, subscriptionsOfTypes } from './types.ts'
import type { StepProps } from './types.ts'

const PT_TYPES = ['PT_ANNUAL', 'PT_MONTHLY']
const OTHER_SUBSCRIPTION_TYPES = [
  'RAIL_SUBSCRIPTION',
  'BIKE_SHARING_SUBSCRIPTION',
  'CAR_SHARING_SUBSCRIPTION',
]

export function MobilityStep({ form, setForm, options }: StepProps) {
  const vehicles = optionsWithIds(options, OTHER_VEHICLE_OPTION_IDS)
  const ptPasses = subscriptionsOfTypes(options, PT_TYPES)
  const otherSubscriptions = subscriptionsOfTypes(options, OTHER_SUBSCRIPTION_TYPES)

  return (
    <>
      <p className="lead">
        Moto, bici e abbonamenti già pagati cambiano il costo di partenza e cosa vale la pena
        aggiungere.
      </p>

      <section className="card">
        <h3>Altri mezzi che possedete</h3>
        {vehicles.map((vehicle) => (
          <Field key={vehicle.id} label={vehicle.name}>
            <Stepper
              label={vehicle.name}
              value={countOtherVehicles(form, vehicle.id)}
              min={0}
              max={MAX_PER_OTHER_VEHICLE}
              onChange={(count) =>
                setForm((current) => setOtherVehicleCount(current, vehicle.id, count))
              }
            />
          </Field>
        ))}
      </section>

      <h3 className="section-title">Abbonamenti</h3>
      <p className="hint">
        Gli abbonamenti scontati (under 27, senior) hanno la fascia d’età nel nome.
      </p>
      {form.adults.map((adult, index) => {
        const patch = (changes: Parameters<typeof updateAdult>[2]) =>
          setForm((current) => updateAdult(current, adult.id, changes))
        return (
          <section key={adult.id} className="card">
            <h3>Adulto {index + 1}</h3>
            <fieldset className="plain">
              <legend className="field-label">Trasporto pubblico</legend>
              <label className="check">
                <input
                  type="radio"
                  name={`pt-${adult.id}`}
                  checked={adult.ptPassOptionId === null}
                  onChange={() => patch({ ptPassOptionId: null })}
                />
                Nessun abbonamento
              </label>
              {ptPasses.map((pass) => (
                <label key={pass.id} className="check">
                  <input
                    type="radio"
                    name={`pt-${adult.id}`}
                    checked={adult.ptPassOptionId === pass.id}
                    onChange={() => patch({ ptPassOptionId: pass.id })}
                  />
                  {pass.name}
                </label>
              ))}
            </fieldset>
            <fieldset className="plain">
              <legend className="field-label">Altri abbonamenti</legend>
              {otherSubscriptions.map((subscription) => (
                <label key={subscription.id} className="check">
                  <input
                    type="checkbox"
                    checked={adult.otherSubscriptionIds.includes(subscription.id)}
                    onChange={(event) =>
                      patch({
                        otherSubscriptionIds: event.target.checked
                          ? [...adult.otherSubscriptionIds, subscription.id]
                          : adult.otherSubscriptionIds.filter((id) => id !== subscription.id),
                      })
                    }
                  />
                  {subscription.name}
                </label>
              ))}
            </fieldset>
          </section>
        )
      })}
    </>
  )
}
