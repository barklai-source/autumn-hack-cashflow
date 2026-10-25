import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api/client'
import { Shell } from './components/Shell'
import { LoginPage } from './pages/LoginPage'
import type { AuthSession } from './types/api'
import './styles.css'
import './counterparty.css'

const Dashboard = lazy(() => import('./pages/Dashboard').then((module) => ({ default: module.Dashboard })))
const ForecastPage = lazy(() => import('./pages/ForecastPage').then((module) => ({ default: module.ForecastPage })))
const OperationsPage = lazy(() => import('./pages/OperationsPage').then((module) => ({ default: module.OperationsPage })))
const CategoriesPage = lazy(() => import('./pages/CategoriesPage').then((module) => ({ default: module.CategoriesPage })))
const RecurringPage = lazy(() => import('./pages/RecurringPage').then((module) => ({ default: module.RecurringPage })))
const EventsPage = lazy(() => import('./pages/EventsPage').then((module) => ({ default: module.EventsPage })))
const QualityPage = lazy(() => import('./pages/QualityPage').then((module) => ({ default: module.QualityPage })))
const CompaniesPage = lazy(() => import('./pages/CompaniesPage').then((module) => ({ default: module.CompaniesPage })))

function Application() {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
  }))
  const [session, setSession] = useState<AuthSession | null>(() => api.getSession())
  const [checkingSession, setCheckingSession] = useState(() => Boolean(api.getSession()))

  useEffect(() => {
    const stored = api.getSession()
    if (!stored) {
      setCheckingSession(false)
      return
    }
    let active = true
    api.me().then((user) => {
      const refreshed = { ...stored, ...user }
      api.saveSession(refreshed)
      if (active) setSession(refreshed)
    }).catch(() => {
      api.logout()
      if (active) setSession(null)
    }).finally(() => {
      if (active) setCheckingSession(false)
    })
    return () => { active = false }
  }, [])

  const changeSession = (next: AuthSession | null) => {
    client.clear()
    setSession(next)
  }

  return <QueryClientProvider client={client}><BrowserRouter><Suspense fallback={<div className="state">Загружаем страницу…</div>}>
    {checkingSession ? <div className="state">Проверяем сессию…</div> : !session ? <LoginPage onLogin={changeSession} /> : <Routes><Route element={<Shell user={session} onSessionChange={changeSession} onLogout={() => { api.logout(); changeSession(null) }} />}>
    <Route index element={<Dashboard />} />
    <Route path="forecast" element={<ForecastPage />} />
    <Route path="operations" element={<OperationsPage />} />
    <Route path="categories" element={<CategoriesPage />} />
    <Route path="recurring" element={<RecurringPage />} />
    <Route path="events" element={<EventsPage />} />
    <Route path="quality" element={<QualityPage />} />
    <Route path="companies" element={session.role === 'admin' ? <CompaniesPage /> : <Navigate to="/" replace />} />
    <Route path="*" element={<Dashboard />} />
  </Route></Routes>}
  </Suspense></BrowserRouter></QueryClientProvider>
}

export default Application
