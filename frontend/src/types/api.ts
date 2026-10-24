export type Company = {
  company_id: string
  name: string
  inn: string
  legal_form: string
  industry: string
  first_operation_date: string
  last_operation_date: string
  operation_count?: number
  last_balance?: number | null
  balance_date?: string | null
}

export type Page<T> = { items: T[]; total: number; page: number; page_size: number }
export type OperationsResponse = Page<Operation> & { needs_review_count?: number }

export type AuthSession = {
  token: string
  role: 'admin' | 'company'
  company_id: string | null
  display_name: string
  inn: string | null
}

export type AuthUser = Omit<AuthSession, 'token'>
export type InnLookup = {
  found: boolean
  inn: string
  company_id: string | null
  name: string | null
  industry: string | null
}

export type Operation = {
  operation_id: string
  company_id: string
  operation_date: string
  amount: number
  signed_amount: number
  direction: 'поступление' | 'списание'
  counterparty_inn: string
  counterparty_name: string
  payment_purpose: string
  balance_eod: number
  category: string
  category_method: string
  confidence: number
  needs_review: boolean
}

export type Summary = {
  company_id: string
  last_actual_date: string | null
  last_balance: number | null
  balance_date: string | null
  balance_is_current: boolean
  forecast_balance_7: number | null
  forecast_balance_30: number | null
  forecast_balance_90: number | null
  forecast_inflows: number | null
  forecast_outflows: number | null
  upcoming_obligations: number
  first_risk_date: string | null
  max_deficit: number | null
  risk_level: string
  risk_probability: number | null
  selected_model: string
  history_days: number
  observed_days: number
  unobserved_calendar_days: number
  balance_consistency_errors: number
  needs_review_count?: number
}

export type ForecastPoint = {
  date: string
  inflow: number
  outflow: number
  net_flow: number
  baseline_inflow: number
  baseline_outflow: number
  baseline_net_flow: number
  baseline_balance: number | null
  event_flow: number
  forecast_net: number
  balance: number | null
  lower: number | null
  upper: number | null
  uncertain: boolean
}

export type ForecastResult = {
  company_id: string
  horizon: number
  balance_date: string | null
  balance_source: string
  method: string
  selected_model: string
  total_inflow: number
  total_outflow: number
  total_net_flow: number
  baseline_total_net_flow: number
  items: ForecastPoint[]
  history: { date: string; balance: number; inflow: number; outflow: number }[]
  uncertainty_note: string
  risk: {
    first_breach: string | null
    max_deficit: number | null
    zero_deficit: number | null
    probability: number | null
    risk_level: string
    method: string
  }
  warning: {
    date: string
    deficit: number
    probability: number | null
    reasons: string
    action: string
  } | null
}

export type RisksResult = {
  risk: Record<string, unknown>
  warning: ForecastResult['warning']
  influencing_events: { date: string; amount: number; description: string }[]
  method: string
  horizon_days: number
}

export type EventItem = {
  id: number
  company_id: string
  date: string
  amount: number
  direction: 'поступление' | 'списание'
  category: string
  event_type: string
  description: string
  source: string
  status: 'Ожидается' | 'Подтверждено' | 'Исполнено' | 'Отменено'
}

export type RecurringItem = {
  recurring_id: string
  account: string
  counterparty: string
  direction: string
  category: string
  frequency: string
  amount: number
  next_date: string
  observations: number
  confidence: number
  confirmed: boolean
}

export type CategoryResponse = {
  by_direction: Record<string, { category: string; amount: number; operations: number; share: number }[]>
  monthly: { month: string; direction: string; category: string; flow_amount: number }[]
}

export type Evaluation = {
  selected_method: string
  forecast_method: string
  metrics: Record<string, string | number | null>[]
  balance_horizons: Record<string, string | number | null>[]
  backtest: { date: string; method: string; actual_net: number; predicted_net: number }[]
}
