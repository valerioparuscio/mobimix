import { type ScenarioValues, toBody } from '../results/scenario.ts'
import type { AnalysisResult } from './results.ts'
import type {
  HealthStatus,
  MobilityOptionSummary,
  QuestionnaireConfig,
  UserProfile,
} from './types.ts'

// Calls go to the same origin; the Vite dev server proxies /api to the backend.
async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export function getHealth(): Promise<HealthStatus> {
  return getJson<HealthStatus>('/api/health')
}

export function getQuestionnaire(): Promise<QuestionnaireConfig> {
  return getJson<QuestionnaireConfig>('/api/reference/questionnaire')
}

export function getMobilityOptions(): Promise<MobilityOptionSummary[]> {
  return getJson<MobilityOptionSummary[]>('/api/reference/mobility-options')
}

export function getDemoHouseholds(): Promise<Record<string, UserProfile>> {
  return getJson<Record<string, UserProfile>>('/api/reference/demo-households')
}

export type AnalyzeOutcome =
  | { kind: 'ok'; result: AnalysisResult }
  | { kind: 'not-ready'; message: string }
  | { kind: 'invalid'; problems: string[] }
  | { kind: 'error'; message: string }

interface ValidationDetail {
  loc?: (string | number)[]
  msg?: string
}

/** Turns FastAPI's validation errors into short lines a person can act on. */
export function describeValidationProblems(detail: unknown): string[] {
  if (!Array.isArray(detail)) return []
  return (detail as ValidationDetail[]).map((item) => {
    const where = (item.loc ?? []).filter((part) => part !== 'body').join(' › ')
    return where ? `${where}: ${item.msg ?? 'valore non valido'}` : (item.msg ?? 'valore non valido')
  })
}

async function postAnalysis(
  path: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<AnalyzeOutcome> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch {
    return { kind: 'error', message: 'Il server non risponde. Controlla che sia avviato.' }
  }

  const body: unknown = await response.json().catch(() => null)
  const detail = (body as { detail?: unknown } | null)?.detail

  if (response.ok) return { kind: 'ok', result: body as AnalysisResult }
  if (response.status === 501) {
    return {
      kind: 'not-ready',
      message: typeof detail === 'string' ? detail : "L'analisi non è ancora disponibile.",
    }
  }
  if (response.status === 422) {
    return { kind: 'invalid', problems: describeValidationProblems(detail) }
  }
  return { kind: 'error', message: `Errore imprevisto del server (HTTP ${response.status}).` }
}

/** Runs the analysis: demand, current cost, alternatives, recommendations (AnalysisResult). */
export function analyze(profile: UserProfile): Promise<AnalyzeOutcome> {
  return postAnalysis('/api/analyze', profile)
}

/** The same analysis under what-if assumptions (fuel price, parking, remote work...). */
export function runScenario(
  profile: UserProfile,
  values: ScenarioValues,
  signal?: AbortSignal,
): Promise<AnalyzeOutcome> {
  return postAnalysis('/api/scenario', { profile, scenario: toBody(values) }, signal)
}
