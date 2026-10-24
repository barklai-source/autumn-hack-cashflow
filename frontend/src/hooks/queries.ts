import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ForecastScenario } from '../api/client'

const DEFAULT_FORECAST_SCENARIO: ForecastScenario = {
  inflow_change_pct: 0,
  outflow_change_pct: 0,
  daily_net_adjustment: 0,
  delay_days: 0,
  shock_amount: 0,
  shock_date: '',
}

export const keys = {
  health: ['health'] as const,
  companies: (search: string) => ['companies', search] as const,
  overview: ['companies-overview'] as const,
  summary: (id: string, horizon: number, reserve: number) => ['summary', id, horizon, reserve] as const,
  operations: (id: string, params: string) => ['operations', id, params] as const,
  categories: (id: string) => ['categories', id] as const,
  recurring: (id: string) => ['recurring', id] as const,
  forecast: (id: string, horizon: number, reserve: number, scenario: ForecastScenario) =>
    ['forecast', id, horizon, reserve, scenario] as const,
  evaluation: (id: string) => ['evaluation', id] as const,
  events: (id: string) => ['events', id] as const,
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health, retry: 1 })
}

export function useCompanies(search = '') {
  return useQuery({ queryKey: keys.companies(search), queryFn: () => api.companies(search) })
}

export function useSummary(id: string | undefined, horizon: number, reserve: number) {
  return useQuery({ queryKey: keys.summary(id ?? '', horizon, reserve), queryFn: () => api.summary(id!, horizon, reserve), enabled: Boolean(id) })
}

export function useForecast(
  id: string | undefined,
  horizon: number,
  reserve: number,
  scenario: ForecastScenario = DEFAULT_FORECAST_SCENARIO,
) {
  return useQuery({
    queryKey: keys.forecast(id ?? '', horizon, reserve, scenario),
    queryFn: () => api.forecast(id!, horizon, reserve, scenario),
    enabled: Boolean(id),
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === (id ?? '') ? previousData : undefined,
  })
}

export function useRisks(id: string | undefined, horizon: number, reserve: number) {
  return useQuery({
    queryKey: ['risks', id ?? '', horizon, reserve],
    queryFn: () => api.risks(id!, horizon, reserve),
    enabled: Boolean(id),
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === (id ?? '') ? previousData : undefined,
  })
}
