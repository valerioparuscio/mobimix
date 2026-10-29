import { Field, Stepper } from '../components/controls.tsx'
import { MAX_ADULTS, MAX_CHILDREN, setAdultCount, setChildCount } from '../form/actions.ts'
import type { StepProps } from './types.ts'

export function HouseholdStep({ form, setForm }: StepProps) {
  return (
    <>
      <p className="lead">
        Partiamo da voi: serve a capire quanti spostamenti ci sono e chi può guidare.
      </p>
      <Field label="Quanti adulti ci sono in famiglia?">
        <Stepper
          label="adulti"
          value={form.adults.length}
          min={1}
          max={MAX_ADULTS}
          onChange={(count) => setForm((current) => setAdultCount(current, count))}
        />
      </Field>
      <Field label="E quanti figli (o minorenni)?">
        <Stepper
          label="figli"
          value={form.nChildren}
          min={0}
          max={MAX_CHILDREN}
          onChange={(count) => setForm((current) => setChildCount(current, count))}
        />
      </Field>
    </>
  )
}
