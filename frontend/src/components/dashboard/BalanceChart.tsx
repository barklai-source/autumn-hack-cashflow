import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ForecastPoint } from '../../types/api'
import { currency, dateRu } from '../../utils/format'

export function BalanceChart({ points, history = [], reserve = 0, scenarioLabel = 'Негативный сценарий (Что если)' }: {
  points: ForecastPoint[]
  history?: { date: string; balance: number; inflow: number; outflow: number }[]
  reserve?: number
  scenarioLabel?: string
}) {
  const data = [
    ...history.map((point) => ({ date: point.date, actualBalance: point.balance, balance: null, baselineBalance: null, lower: null, upper: null, inflow: point.inflow, outflow: point.outflow, event_flow: 0 })),
    ...points.map((point) => ({
      ...point,
      actualBalance: null,
      baselineBalance: point.baseline_balance,
      scenarioBalance: point.balance,
    })),
  ].sort((left, right) => left.date.localeCompare(right.date)).map((point) => ({
    ...point, shortDate: new Date(point.date).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }),
  }))
  if (!data.length) return <div className="empty-state">Нет прогноза для отображения.</div>
  return <div className="chart-wrap">
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 12, right: 12, left: 12, bottom: 0 }}>
        <defs><linearGradient id="balanceFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#28a879" stopOpacity={0.19} /><stop offset="100%" stopColor="#28a879" stopOpacity={0.01} /></linearGradient></defs>
        <CartesianGrid stroke="#edf0f5" vertical={false} />
        <XAxis dataKey="shortDate" tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tickFormatter={(value: number) => `${Math.round(value / 1000)} тыс.`} tickLine={false} axisLine={false} width={64} />
        <Tooltip wrapperStyle={{ pointerEvents: 'none' }} labelFormatter={(_, entries) => dateRu(entries[0]?.payload.date)} formatter={(value, name) => [currency(Number(value)), String(name)]} />
        <Legend />
        <ReferenceLine y={0} stroke="#db6c6c" strokeDasharray="5 5" label="Ноль" />
        {reserve > 0 && <ReferenceLine y={reserve} stroke="#e5a53d" strokeDasharray="4 4" label="Резерв" />}
        <Area type="monotone" dataKey="upper" stroke="none" fill="transparent" name="Верхняя оценка" connectNulls />
        <Area type="monotone" dataKey="lower" stroke="none" fill="url(#balanceFill)" name="Диапазон оценки" connectNulls />
        <Line type="monotone" dataKey="actualBalance" stroke="#3978c5" strokeWidth={2} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="Фактический остаток" connectNulls={false} />
        <Line type="monotone" dataKey="baselineBalance" stroke="#258a6a" strokeWidth={2.5} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="Базовый прогноз остатка" connectNulls />
        <Line type="monotone" dataKey="scenarioBalance" stroke="#9b59b6" strokeWidth={2.5} strokeDasharray="7 5" dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name={scenarioLabel} connectNulls />
        <Line type="monotone" dataKey="event_flow" stroke="#d4952e" strokeWidth={1} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="События, чистый поток" />
      </AreaChart>
    </ResponsiveContainer>
  </div>
}

export function NetCashFlowChart({ points }: { points: ForecastPoint[] }) {
  if (!points.length) return <div className="empty-state">Нет потоков для отображения.</div>
  const data = points.map((point) => ({
    ...point,
    shortDate: new Date(point.date).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }),
  }))
  return <div className="chart-wrap">
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data} margin={{ top: 12, right: 12, left: 12, bottom: 0 }}>
        <CartesianGrid stroke="#edf0f5" vertical={false} />
        <XAxis dataKey="shortDate" tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tickFormatter={(value: number) => `${Math.round(value / 1000)} тыс.`} tickLine={false} axisLine={false} width={64} />
        <Tooltip wrapperStyle={{ pointerEvents: 'none' }} labelFormatter={(_, entries) => dateRu(entries[0]?.payload.date)} formatter={(value, name) => [currency(Number(value)), String(name)]} />
        <Legend />
        <ReferenceLine y={0} stroke="#a8b2bd" />
        <Bar dataKey="inflow" fill="#28a879" fillOpacity={0.72} name="Поступления" />
        <Bar dataKey="outflow" fill="#e27474" fillOpacity={0.72} name="Списания" />
        <Line type="monotone" dataKey="net_flow" stroke="#376fbd" strokeWidth={2.5} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="Чистый поток" />
      </ComposedChart>
    </ResponsiveContainer>
  </div>
}

export function PlanFactChart({ points, history }: {
  points: ForecastPoint[]
  history: { date: string; balance: number; inflow: number; outflow: number }[]
}) {
  const recentHistory = history.slice(-35)
  const historyData = recentHistory.slice(-28).map((actual) => {
    const actualDate = new Date(`${actual.date.slice(0, 10)}T00:00:00`)
    const weekday = actualDate.getDay()
    const priorValues = recentHistory
      .filter((candidate) => candidate.date < actual.date && new Date(`${candidate.date.slice(0, 10)}T00:00:00`).getDay() === weekday)
      .slice(-4)
    const average = (field: 'inflow' | 'outflow') => priorValues.length
      ? priorValues.reduce((sum, candidate) => sum + candidate[field], 0) / priorValues.length
      : null
    return {
      date: actual.date,
      actualInflow: actual.inflow,
      actualOutflow: actual.outflow,
      plannedInflow: average('inflow'),
      plannedOutflow: average('outflow'),
    }
  })
  const forecastData = points.map((point) => ({
    date: point.date,
    actualInflow: null,
    actualOutflow: null,
    plannedInflow: point.baseline_inflow,
    plannedOutflow: point.baseline_outflow,
  }))
  const data = [...historyData, ...forecastData].map((point) => ({
    ...point,
    shortDate: new Date(`${point.date.slice(0, 10)}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }),
  }))
  if (!data.length) return <div className="empty-state">Нет данных для план-факта.</div>
  return <div className="chart-wrap">
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data} margin={{ top: 12, right: 12, left: 12, bottom: 0 }}>
        <CartesianGrid stroke="#edf0f5" vertical={false} />
        <XAxis dataKey="shortDate" tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tickFormatter={(value: number) => `${Math.round(value / 1000)} тыс.`} tickLine={false} axisLine={false} width={64} />
        <Tooltip wrapperStyle={{ pointerEvents: 'none' }} labelFormatter={(_, entries) => dateRu(entries[0]?.payload.date)} formatter={(value, name) => [currency(Number(value)), String(name)]} />
        <Legend />
        <Line type="monotone" dataKey="actualInflow" stroke="#258a6a" strokeWidth={2} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="Факт поступлений" connectNulls={false} />
        <Line type="monotone" dataKey="plannedInflow" stroke="#258a6a" strokeDasharray="5 4" dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="План поступлений" connectNulls={false} />
        <Line type="monotone" dataKey="actualOutflow" stroke="#d16b6b" strokeWidth={2} dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="Факт списаний" connectNulls={false} />
        <Line type="monotone" dataKey="plannedOutflow" stroke="#d16b6b" strokeDasharray="5 4" dot={false} activeDot={{ r: 4, pointerEvents: 'none' }} isAnimationActive={false} name="План списаний" connectNulls={false} />
      </ComposedChart>
    </ResponsiveContainer>
  </div>
}
