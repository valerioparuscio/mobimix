import type { Occupation } from '../api/types.ts'
import { Chips, Field, NumericField, Stepper } from '../components/controls.tsx'
import { updateAdult } from '../form/actions.ts'
import { OCCUPATION_LABELS, TWO_WHEELS_LABELS, TWO_WHEELS_ORDER } from '../form/labels.ts'
import { worksOrStudies } from '../form/rules.ts'
import { BAND_GROUPS } from '../form/types.ts'
import type { StepProps } from './types.ts'

const OCCUPATIONS = (Object.keys(OCCUPATION_LABELS) as Occupation[]).map((value) => ({
  value,
  label: OCCUPATION_LABELS[value],
}))

const TWO_WHEELS = TWO_WHEELS_ORDER.map((value) => ({
  value,
  label: TWO_WHEELS_LABELS[value],
}))

export function WorkStep({ form, setForm, config }: StepProps) {
  const distanceGroup = config.groups[BAND_GROUPS.distanceKm]

  return (
    <>
      <p className="lead">
        Gli spostamenti casa-lavoro o casa-scuola sono i più regolari: li chiediamo per ogni adulto.
      </p>
      {form.adults.map((adult, index) => {
        const patch = (changes: Parameters<typeof updateAdult>[2]) =>
          setForm((current) => updateAdult(current, adult.id, changes))
        return (
          <section key={adult.id} className="card">
            <h3>Adulto {index + 1}</h3>
            <Field label="Di cosa si occupa?">
              <Chips
                label={`Occupazione adulto ${index + 1}`}
                options={OCCUPATIONS}
                value={adult.occupation}
                onChange={(occupation) => patch({ occupation })}
              />
            </Field>
            <label className="check">
              <input
                type="checkbox"
                checked={adult.hasLicense}
                onChange={(event) => patch({ hasLicense: event.target.checked })}
              />
              Ha la patente di guida
            </label>
            <Field
              label="Usa la bici, l’e-bike o lo scooter?"
              hint="Non tutti possono o vogliono, soprattutto quando piove: se non li usa, non li proponiamo."
            >
              <Chips
                label={`Bici, e-bike e scooter adulto ${index + 1}`}
                options={TWO_WHEELS}
                value={adult.twoWheels}
                onChange={(twoWheels) => patch({ twoWheels })}
              />
            </Field>

            {worksOrStudies(adult) && distanceGroup && (
              <>
                <NumericField
                  label="Quanto dista il posto di lavoro o di studio da casa? (solo andata)"
                  group={distanceGroup}
                  value={adult.distanceKm}
                  onChange={(distanceKm) => patch({ distanceKm })}
                />
                <Field label="Quanti giorni a settimana ci va di solito?">
                  <Stepper
                    label="giorni a settimana"
                    value={adult.daysPerWeek}
                    min={1}
                    max={7}
                    onChange={(daysPerWeek) =>
                      patch({
                        daysPerWeek,
                        remoteDaysPerWeek: Math.min(adult.remoteDaysPerWeek, daysPerWeek),
                      })
                    }
                  />
                </Field>
                <Field label="Di questi, quanti li fa da remoto?">
                  <Stepper
                    label="giorni da remoto"
                    value={adult.remoteDaysPerWeek}
                    min={0}
                    max={adult.daysPerWeek}
                    onChange={(remoteDaysPerWeek) => patch({ remoteDaysPerWeek })}
                  />
                </Field>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={adult.timeCritical}
                    onChange={(event) => patch({ timeCritical: event.target.checked })}
                  />
                  Deve arrivare a un orario preciso (i ritardi sono un problema)
                </label>
              </>
            )}
          </section>
        )
      })}
    </>
  )
}
