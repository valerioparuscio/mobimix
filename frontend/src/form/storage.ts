// Draft persistence in the browser (MVP: no accounts, nothing is stored on the server).
// localStorage can be missing, full or blocked (private windows): every access is guarded and
// the questionnaire works without it.

import type { FormState, StepId } from './types.ts'

const KEY = 'mobimix.draft.v1'

export interface Draft {
  version: 1
  step: StepId
  form: FormState
}

export function saveDraft(draft: Draft): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(draft))
  } catch {
    // ignore: persistence is a convenience only
  }
}

export function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null) return null
    const draft = JSON.parse(raw) as Partial<Draft> | null
    if (draft?.version !== 1 || !draft.form || !Array.isArray(draft.form.adults)) return null
    if (typeof draft.step !== 'string') return null
    return draft as Draft
  } catch {
    return null
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}
