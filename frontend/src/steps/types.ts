import type { MobilityOptionSummary, QuestionnaireConfig } from '../api/types.ts'
import type { FormState } from '../form/types.ts'

/** What every questionnaire step receives. */
export interface StepProps {
  form: FormState
  setForm: (update: (form: FormState) => FormState) => void
  config: QuestionnaireConfig
  options: MobilityOptionSummary[]
}

/** The catalogue options with the given ids, in that order (missing ids are skipped). */
export function optionsWithIds(
  options: MobilityOptionSummary[],
  ids: readonly string[],
): MobilityOptionSummary[] {
  return ids.flatMap((id) => options.filter((option) => option.id === id))
}

/** Subscription options of the given catalogue types, in catalogue order. */
export function subscriptionsOfTypes(
  options: MobilityOptionSummary[],
  types: readonly string[],
): MobilityOptionSummary[] {
  return options.filter(
    (option) => option.ownership === 'SUBSCRIPTION' && types.includes(option.type),
  )
}
