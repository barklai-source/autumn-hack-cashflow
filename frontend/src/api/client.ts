import type {
  AuthSession, AuthUser, CategoryResponse, Company, Evaluation, EventItem, ForecastResult, InnLookup, OperationsResponse, Page, RecurringItem, RisksResult, Summary,
} from '../types/api'

export type ForecastScenario = {
  inflow_change_pct: number
  outflow_change_pct: number
  daily_net_adjustment: number
  delay_days: number
  shock_amount: number
  shock_date: string
}

const API_ROOT = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api'
const AUTH_STORAGE_KEY = 'cashflow-auth-session'

function readSession(): AuthSession | null {
  try {
    const value = localStorage.getItem(AUTH_STORAGE_KEY)
    if (!value) return null
    const session = JSON.parse(value) as AuthSession
    if (!session.token || !['admin', 'company'].includes(session.role)) return null
    return session
  } catch {
    return null
  }
}

function saveSession(session: AuthSession) {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
}

function clearSession() {
  localStorage.removeItem(AUTH_STORAGE_KEY)
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const session = readSession()
  if (session?.token) headers.set('Authorization', `Bearer ${session.token}`)
  const response = await fetch(`${API_ROOT}${path}`, { ...init, headers })
  if (!response.ok) {
    let message = `Ошибка API (${response.status})`
    try {
      const payload = await response.json() as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      message = response.statusText || message
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  getSession: readSession,
  saveSession,
  logout: clearSession,
  login: async (username: string, password: string) => {
    const session = await request<AuthSession>('/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
    })
    saveSession(session)
    return session
  },
  demoCompanies: () =>
    request<{ items: Pick<Company, 'company_id' | 'name' | 'inn'>[] }>('/auth/demo-companies'),
  lookupInn: (inn: string) =>
    request<InnLookup>(`/auth/lookup-inn?inn=${encodeURIComponent(inn)}`),
  register: async (inn: string, password: string, company_name?: string) => {
    const session = await request<AuthSession>('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inn, password, company_name }),
    })
    saveSession(session)
    return session
  },
  me: () => request<AuthUser>('/auth/me'),
  health: () => request<{ status: string; data_available: boolean; companies: number; operations: number; message: string }>('/health'),
  companies: (search = '') => request<Page<Company>>(`/companies?page=1&page_size=200${search ? `&search=${encodeURIComponent(search)}` : ''}`),
  overview: () => request<{ companies: number; operations: number; rows: Company[] }>('/companies/overview'),
  reloadDataset: () =>
    request<{ status: string; message: string; companies: Company[]; total: number; errors: string[] }>('/admin/reload-dataset', {
      method: 'POST',
    }),
  summary: (id: string, horizon: number, reserve: number) => request<Summary>(`/companies/${id}/summary?horizon=${horizon}&reserve=${reserve}`),
  operations: (id: string, params: URLSearchParams) => request<OperationsResponse>(`/companies/${id}/operations?${params}`),
  categories: (id: string) => request<CategoryResponse>(`/companies/${id}/categories`),
  recurring: (id: string) => request<{ items: RecurringItem[] }>(`/companies/${id}/recurring`),
  forecast: (id: string, horizon: number, reserve: number, scenario: ForecastScenario) => {
    const params = new URLSearchParams({ horizon: String(horizon), reserve: String(reserve) })
    Object.entries(scenario).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    })
    return request<ForecastResult>(`/companies/${id}/forecast?${params}`)
  },
  risks: (id: string, horizon: number, reserve: number) =>
    request<RisksResult>(`/companies/${id}/risks?horizon=${horizon}&reserve=${reserve}`),
  evaluation: (id: string) => request<Evaluation>(`/companies/${id}/model-evaluation`),
  events: (id: string) => request<{ items: EventItem[] }>(`/companies/${id}/events`),
  resetDemoEvents: (companyId: string) =>
    request<{ items: EventItem[] }>(`/companies/${companyId}/events/reset-demo`, { method: 'POST' }),
  changeCategory: (companyId: string, operationId: string, category: string) =>
    request(`/companies/${companyId}/operations/${encodeURIComponent(operationId)}/category`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ category }),
    }),
  confirmRecurring: (companyId: string, recurringId: string, confirmed: boolean) =>
    request(`/companies/${companyId}/recurring/${recurringId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed }),
    }),
  createEvent: (companyId: string, event: Omit<EventItem, 'id' | 'company_id'>) =>
    request<EventItem>(`/companies/${companyId}/events`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
    }),
  updateEvent: (companyId: string, eventId: number, event: Partial<EventItem>) =>
    request<EventItem>(`/companies/${companyId}/events/${eventId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
    }),
  cancelEvent: (companyId: string, eventId: number) =>
    request<EventItem>(`/companies/${companyId}/events/${eventId}`, { method: 'DELETE' }),
  importEvents: (companyId: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<{ imported: number }>(`/companies/${companyId}/events/import`, { method: 'POST', body })
  },
}
