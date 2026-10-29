import { NumericField } from '../components/controls.tsx'
import { isNone } from '../form/rules.ts'
import type { FormState, NumericForm } from '../form/types.ts'
import { BAND_GROUPS } from '../form/types.ts'
import type { StepProps } from './types.ts'

type NumericKey =
  | 'weekendTrips'
  | 'weekendDistanceKm'
  | 'holidayTrips'
  | 'holidayDistanceKm'
  | 'taxiTrips'
  | 'carSharingTrips'
  | 'carRentalDays'

export function OccasionalStep({ form, setForm, config }: StepProps) {
  function field(key: NumericKey, label: string, hint?: string) {
    const group = config.groups[BAND_GROUPS[key]]
    if (!group) return null
    return (
      <NumericField
        label={label}
        hint={hint}
        group={group}
        value={form[key]}
        onChange={(value: NumericForm) =>
          setForm((current: FormState) => ({ ...current, [key]: value }))
        }
      />
    )
  }

  const noWeekendTrips = isNone(form.weekendTrips, config.groups[BAND_GROUPS.weekendTrips])
  const noHolidays = isNone(form.holidayTrips, config.groups[BAND_GROUPS.holidayTrips])

  return (
    <>
      <p className="lead">
        Gite, vacanze e servizi a consumo: bastano risposte approssimative, il resto lo stimiamo.
      </p>

      <section className="card">
        <h3>Weekend</h3>
        {field('weekendTrips', 'Quante gite di un giorno fate nel weekend, in un anno?')}
        {!noWeekendTrips &&
          field('weekendDistanceKm', 'Quanto lontano vi spostate di solito? (solo andata)')}
      </section>

      <section className="card">
        <h3>Vacanze</h3>
        {field('holidayTrips', 'Quanti viaggi di vacanza fate in un anno?')}
        {!noHolidays &&
          field('holidayDistanceKm', 'Quanto lontano vi spostate di solito? (solo andata)')}
      </section>

      <section className="card">
        <h3>Servizi a consumo</h3>
        {field('taxiTrips', 'Quanto usate il taxi?')}
        {field('carSharingTrips', 'Quanto usate il car sharing?')}
        {field('carRentalDays', 'Quanto noleggiate un’auto?')}
      </section>
    </>
  )
}
