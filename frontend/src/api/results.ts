// What `POST /api/analyze` returns (mirrors backend/app/models/evaluation.py, portfolio.py and
// recommendation.py), reduced to the fields the results screen reads. Hand-written like
// ./types.ts, and to be generated from the OpenAPI schema with it.

export interface Range {
  low: number
  expected: number
  high: number
}

export type Confidence = 'LOW' | 'MEDIUM' | 'HIGH'

export type Role = 'CURRENT' | 'CHEAPEST' | 'BALANCED' | 'FASTEST' | 'MOST_COMFORTABLE'

export type Category =
  | 'KEEP_CURRENT'
  | 'OPTIMIZE_USAGE'
  | 'CHANGE_SUBSCRIPTION'
  | 'ADD_ASSET'
  | 'REPLACE_VEHICLE'
  | 'REDUCE_VEHICLES'
  | 'CHANGE_PORTFOLIO'

export type Strength =
  | 'KEEP_CURRENT'
  | 'SMALL_IMPROVEMENT'
  | 'CONSIDER_CHANGE'
  | 'STRONG_OPPORTUNITY'

export interface PortfolioItem {
  option_id: string
  holder_id: string | null
  quantity: number
  profile_ref: string | null
}

export interface PortfolioChange {
  kind: 'SELL_VEHICLE' | 'BUY_VEHICLE' | 'CANCEL_SUBSCRIPTION' | 'START_SUBSCRIPTION'
  option_id: string
  holder_id: string | null
}

export interface Portfolio {
  id: string
  name: string
  origin: 'CURRENT' | 'GENERATED'
  items: PortfolioItem[]
  description: string | null
  changes: PortfolioChange[]
}

export interface PortfolioDelta {
  cost: Range
  travel_hours: Range
  perceived_hours: Range
  comfort: Range
  flexibility: Range
  car_km: Range
  co2_kg: Range | null
  saving_per_extra_hour: number | null
}

export interface PortfolioEvaluation {
  portfolio_id: string
  annual_cost: Range
  annual_travel_hours: Range
  comfort: Range
  flexibility: Range
  car_km_per_year: Range
  co2_kg_per_year: Range | null
  private_vehicles_owned: number
  delta: PortfolioDelta | null
  confidence: Confidence
  data_quality_notes: string[]
}

export interface ExplanationFact {
  code: string
  values: Record<string, number | string>
}

export interface Recommendation {
  portfolio_id: string
  roles: Role[]
  category: Category
  strength: Strength
  delta: PortfolioDelta | null
  change_penalty: number | null
  net_benefit: Range | null
  facts: ExplanationFact[]
  explanation: string[]
  confidence: Confidence
}

export interface AccuracyHint {
  field: string
  message: string
  reduction_eur: number
}

export interface RecommendationSet {
  recommendations: Recommendation[]
  headline_portfolio_id: string
  pareto_portfolio_ids: string[]
  accuracy_hints: AccuracyHint[]
}

export interface FeasibilityIssue {
  mission_id: string | null
  severity: 'BLOCKING' | 'WARNING'
  code: string
  message: string
}

export interface RejectedPortfolio {
  portfolio_id: string
  name: string
  description: string | null
  issues: FeasibilityIssue[]
}

/** The what-if assumptions of `POST /api/scenario`; each change is a fraction (0.2 is +20%). */
export interface ScenarioBody {
  extra_remote_days_per_week: number
  fuel_price_change: number
  parking_cost_change: number
  car_km_change: number
  ebike_subsidy_eur: number
}

export interface AnalysisResult {
  profile_id: string
  /** The assumptions the analysis was run with; null for the household as it is. */
  scenario: ScenarioBody | null
  parameters_version: string | null
  portfolios: Portfolio[]
  current: PortfolioEvaluation
  evaluations: PortfolioEvaluation[]
  rejected: RejectedPortfolio[]
  recommendations: RecommendationSet
}
