// Adaptive rules of the questionnaire (CLAUDE.md section 13): which questions apply, and what
// must be answered before moving on. Pure functions of the form state.

import type { BandGroup } from '../api/types.ts'
import type { AdultForm, FormState, NumericForm, StepId } from './types.ts'

export const STEP_ORDER: readonly StepId[] = [
  'household',
  'location',
  'work',
  'cars',
  'mobility',
  'occasional',
  'preferences',
  'summary',
]

export const STEP_TITLES: Record<StepId, string> = {
  household: 'Chi siete',
  location: 'Dove abitate',
  work: 'Lavoro e studio',
  cars: 'Le vostre auto',
  mobility: 'Altri mezzi e abbonamenti',
  occasional: 'Weekend, vacanze e servizi',
  preferences: 'Cosa conta di più',
  summary: 'Riepilogo',
}

export function worksOrStudies(adult: AdultForm): boolean {
  return adult.occupation === 'WORKER' || adult.occupation === 'STUDENT'
}

/** Kilometres and parking are asked only for cars the household owns. */
export function showCarDetails(form: FormState): boolean {
  return form.cars.length >= 1
}

/** "How often are two cars needed at the same time?" only makes sense with 2+ cars. */
export function showSimultaneity(form: FormState): boolean {
  return form.cars.length >= 2
}

/** True when the answer is "none" (exact 0, or a band whose upper end is 0). Used to skip
 * follow-up questions: no weekend trips -> no need to ask how far they go. */
export function isNone(value: NumericForm, group: BandGroup | undefined): boolean {
  if (value.kind === 'exact') return value.value === 0
  if (value.kind === 'band') {
    const band = group?.bands.find((candidate) => candidate.id === value.bandId)
    return band !== undefined && band.high === 0
  }
  return false
}

/** Reasons the user cannot continue from a step yet, in plain language. Empty = complete. */
export function stepProblems(step: StepId, form: FormState): string[] {
  const problems: string[] = []
  switch (step) {
    case 'location':
      if (form.areaType === null) problems.push('Scegli il tipo di zona in cui abitate.')
      break
    case 'work':
      form.adults.forEach((adult, index) => {
        if (worksOrStudies(adult) && adult.remoteDaysPerWeek > adult.daysPerWeek) {
          problems.push(
            `Adulto ${index + 1}: i giorni da remoto non possono essere più dei giorni di lavoro.`,
          )
        }
      })
      break
    case 'cars':
      form.cars.forEach((car, index) => {
        if (car.optionId === null) problems.push(`Auto ${index + 1}: scegli il tipo di auto.`)
      })
      break
    default:
      break
  }
  return problems
}

export function isStepComplete(step: StepId, form: FormState): boolean {
  return stepProblems(step, form).length === 0
}

/** First step (before the summary) that still has problems, or null if the form is complete. */
export function firstIncompleteStep(form: FormState): StepId | null {
  return STEP_ORDER.find((step) => step !== 'summary' && !isStepComplete(step, form)) ?? null
}
