import { useEffect, useState } from 'react'
import { AlertTriangle, CalendarDays, Download, ShieldAlert, TrendingDown, TrendingUp } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { BalanceChart, NetCashFlowChart, PlanFactChart } from '../components/dashboard/BalanceChart'
import { CalculationTrace } from '../components/CalculationTrace'
import { QueryState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys, useForecast } from '../hooks/queries'
import { api, type ForecastScenario } from '../api/client'
import { currency, dateRu, percent } from '../utils/format'

const BASE_SCENARIO: ForecastScenario = {
  inflow_change_pct: 0,
  outflow_change_pct: 0,
  daily_net_adjustment: 0,
  delay_days: 0,
  shock_amount: 0,
  shock_date: '',
}

function signedCurrency(amount: number) {
  return `${amount > 0 ? '+' : amount < 0 ? '−' : ''}${currency(Math.abs(amount))}`
}

export function ForecastPage() {
  const { company } = useCompanyContext()
  const [horizon, setHorizon] = useState(90)
  const [reserve, setReserve] = useState(250000)
  const [scenario, setScenario] = useState(BASE_SCENARIO)
  const [queryScenario, setQueryScenario] = useState(scenario)
  useEffect(() => {
    const timer = window.setTimeout(() => setQueryScenario(scenario), 225)
    return () => window.clearTimeout(timer)
  }, [scenario])
  const result = useForecast(company?.company_id, horizon, reserve, queryScenario)
  const events = useQuery({
    queryKey: keys.events(company?.company_id ?? ''),
    queryFn: () => api.events(company!.company_id),
    enabled: Boolean(company),
  })
  const items = result.data?.items ?? []
  const firstForecastDate = items[0]?.date.slice(0, 10) ?? ''
  const effectiveShockDate = scenario.shock_date || firstForecastDate
  const active = scenario.inflow_change_pct !== 0
    || scenario.outflow_change_pct !== 0
    || scenario.daily_net_adjustment !== 0
    || scenario.delay_days !== 0
    || scenario.shock_amount !== 0
  const baselineInflows = items.reduce((sum, item) => sum + item.baseline_inflow, 0)
  const baselineOutflows = items.reduce((sum, item) => sum + item.baseline_outflow, 0)
  const baseBalances = items.flatMap((item) => item.baseline_balance === null ? [] : [item.baseline_balance])
  const scenarioBalances = items.flatMap((item) => item.balance === null ? [] : [item.balance])
  const baseMinimum = baseBalances.length ? Math.min(...baseBalances) : null
  const scenarioMinimum = scenarioBalances.length ? Math.min(...scenarioBalances) : null
  const baseBreakDate = items.find((item) => item.baseline_balance !== null && item.baseline_balance < reserve)?.date.slice(0, 10) ?? null
  const scenarioBreakDate = items.find((item) => item.balance !== null && item.balance < reserve)?.date.slice(0, 10) ?? null
  const scenarioBreaksEarlier = Boolean(scenarioBreakDate && (!baseBreakDate || scenarioBreakDate < baseBreakDate))
  const scenarioLabel = scenario.inflow_change_pct > 0
    ? 'Позитивный сценарий (Что если)'
    : 'Негативный сценарий (Что если)'
  const baselineDeficit = baseMinimum === null ? null : Math.max(0, reserve - baseMinimum)
  const scenarioDeficit = scenarioMinimum === null ? null : Math.max(0, reserve - scenarioMinimum)
  const overdueEvents = (events.data?.items ?? []).filter((event) =>
    event.date < new Date().toISOString().slice(0, 10)
    && (event.status === 'Ожидается' || event.status === 'Подтверждено'),
  )
  const isDebouncingScenario = Object.keys(scenario).some((key) =>
    scenario[key as keyof ForecastScenario] !== queryScenario[key as keyof ForecastScenario],
  )

  const updateScenario = <K extends keyof ForecastScenario>(key: K, value: ForecastScenario[K]) => {
    setScenario((current) => ({ ...current, [key]: value }))
  }
  const resetScenario = () => setScenario(BASE_SCENARIO)
  const setPreset = (kind: 'growth' | 'stress' | 'gap') => {
    const shockDate = firstForecastDate
    if (kind === 'growth') {
      setScenario({ ...BASE_SCENARIO, inflow_change_pct: 40 })
    } else if (kind === 'stress') {
      setScenario({ ...BASE_SCENARIO, inflow_change_pct: -35, outflow_change_pct: 20 })
    } else {
      setScenario({
        ...BASE_SCENARIO,
        inflow_change_pct: -25,
        outflow_change_pct: 15,
        daily_net_adjustment: -150000,
        delay_days: 10,
        shock_amount: -500000,
        shock_date: shockDate,
      })
    }
  }
  const downloadCalendar = () => {
    const rows = [
      ['Дата', 'Поступления, ₽', 'Списания, ₽', 'Чистый поток, ₽', 'Остаток, ₽'],
      ...items.map((item) => [
        item.date.slice(0, 10),
        item.inflow.toFixed(2),
        item.outflow.toFixed(2),
        item.net_flow.toFixed(2),
        item.balance?.toFixed(2) ?? '',
      ]),
    ]
    const csv = `\uFEFF${rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(';')).join('\r\n')}`
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `platezhny-kalendar-${company?.company_id ?? 'company'}-${horizon}-days.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return <div className="page-stack">
    <div className="page-heading"><div><div className="eyebrow">ПЛАНИРОВАНИЕ</div><h1>Прогноз и риски</h1><p>Управляйте чистым денежным потоком и проверяйте сценарии в реальном времени.</p></div></div>
    <div className="card filter-card"><label>Горизонт прогноза<select value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}><option value={30}>30 дней</option><option value={60}>60 дней</option><option value={90}>90 дней</option></select></label><label>Минимальный резерв, ₽<input aria-label="Минимальный резерв" type="number" min={0} step={50000} value={reserve} onChange={(event) => setReserve(Math.max(0, Number(event.target.value)))} /></label></div>
    <QueryState isLoading={result.isLoading && !result.data} error={result.error as Error | null}>{result.data && <>
      <section className="card scenario-card">
        <div className="card-heading"><div><h2>Управление чистым потоком и сценарии «Что если»</h2><p>Изменяйте параметры и наблюдайте влияние на прогнозируемые поступления, списания и остаток.</p></div></div>
        <div className="scenario-presets">
          <button className="button secondary" type="button" onClick={resetScenario}>Базовый</button>
          <button className="button secondary" type="button" onClick={() => setPreset('growth')}>Рост потока (+40% выручки)</button>
          <button className="button secondary" type="button" onClick={() => setPreset('stress')}>Стресс / Кризис</button>
          <button className="button secondary" type="button" onClick={() => setPreset('gap')}>Кассовый разрыв</button>
          <button className="button secondary" type="button" onClick={resetScenario}>Сбросить</button>
        </div>
        <div className="scenario-controls">
          <label>Снижение выручки, %<div className="scenario-range"><input aria-label="Снижение выручки, %" type="range" min={0} max={30} step={1} value={Math.max(0, -scenario.inflow_change_pct)} onChange={(event) => updateScenario('inflow_change_pct', -Number(event.target.value))} /><output>{scenario.inflow_change_pct > 0 ? `+${scenario.inflow_change_pct}% рост` : `−${Math.abs(scenario.inflow_change_pct)}%`}</output></div></label>
          <label>Рост постоянных расходов, %<div className="scenario-range"><input aria-label="Рост постоянных расходов, %" type="range" min={0} max={30} step={1} value={Math.max(0, scenario.outflow_change_pct)} onChange={(event) => updateScenario('outflow_change_pct', Number(event.target.value))} /><output>+{Math.max(0, scenario.outflow_change_pct)}%</output></div></label>
          <label>Корректировка чистого потока в день, ₽<div className="scenario-range"><input aria-label="Корректировка потока в день, ползунок" type="range" min={-300000} max={300000} step={5000} value={scenario.daily_net_adjustment} onChange={(event) => updateScenario('daily_net_adjustment', Number(event.target.value))} /><input aria-label="Корректировка потока в день, ₽" type="number" min={-500000} max={500000} step={5000} value={scenario.daily_net_adjustment} onChange={(event) => updateScenario('daily_net_adjustment', Math.max(-500000, Math.min(500000, Number(event.target.value))))} /></div></label>
          <label>Крупный клиент задержал оплату<select aria-label="Срок задержки оплаты" value={scenario.delay_days} onChange={(event) => updateScenario('delay_days', Number(event.target.value))}><option value={0}>Без задержки</option><option value={14}>2 недели</option><option value={21}>3 недели</option><option value={28}>4 недели</option></select></label>
          <label>Разовый платёж / сделка, ₽<input aria-label="Сумма разового платежа со знаком" type="number" step={1000} value={scenario.shock_amount} onChange={(event) => setScenario((current) => ({ ...current, shock_amount: Number(event.target.value), shock_date: current.shock_date || firstForecastDate }))} placeholder="+ поступление / − списание" /></label>
          <label>Дата разового платежа<input aria-label="Дата разового платежа" type="date" min={firstForecastDate} max={items.at(-1)?.date.slice(0, 10)} value={effectiveShockDate} onChange={(event) => updateScenario('shock_date', event.target.value)} disabled={!items.length} /></label>
        </div>
      </section>
      {active && <section className="card scenario-comparison">
        <div className="card-heading"><div><h2>Сравнение кассового разрыва</h2><p>Минимальный остаток сопоставлен с выбранным резервом {currency(reserve)}.</p></div></div>
        <div className="metrics-grid">
          <article className="metric-card"><div className="metric-title">Базовый прогноз</div><div className="metric-value">{baseBreakDate ? dateRu(baseBreakDate) : 'Разрыва нет'}</div><div className="metric-detail">дефицит: {currency(baselineDeficit ?? 0)}</div></article>
          <article className="metric-card"><div className="metric-title">{scenarioLabel}</div><div className="metric-value">{scenarioBreakDate ? dateRu(scenarioBreakDate) : 'Разрыва нет'}</div><div className="metric-detail">дефицит: {currency(scenarioDeficit ?? 0)}{scenarioBreaksEarlier ? ' · наступает раньше' : ''}</div></article>
        </div>
      </section>}
      <div className="metrics-grid scenario-kpis">
        <article className="metric-card"><div className="metric-icon green"><TrendingUp size={19} /></div><div className="metric-title">Суммарные поступления</div><div className="metric-value">{currency(result.data.total_inflow)}</div><div className="metric-detail">база: {currency(baselineInflows)} · Δ {signedCurrency(result.data.total_inflow - baselineInflows)}</div></article>
        <article className="metric-card"><div className="metric-icon rose"><TrendingDown size={19} /></div><div className="metric-title">Суммарные списания</div><div className="metric-value">{currency(result.data.total_outflow)}</div><div className="metric-detail">база: {currency(baselineOutflows)} · Δ {signedCurrency(result.data.total_outflow - baselineOutflows)}</div></article>
        <article className="metric-card"><div className="metric-icon blue"><ShieldAlert size={19} /></div><div className="metric-title">Итоговый чистый поток за период</div><div className="metric-value">{currency(result.data.total_net_flow)}</div><div className="metric-detail">к базе: {signedCurrency(result.data.total_net_flow - result.data.baseline_total_net_flow)}</div></article>
      </div>
      <section className="card chart-card"><div className="card-heading"><div><h2>Прогноз остатка</h2><p>Последний остаток на {dateRu(result.data.balance_date)} · метод: {result.data.method}</p></div><div className="forecast-chart-actions">{(result.isFetching || isDebouncingScenario) && <span className="tag recalculating">Пересчёт...</span>}<button className="button secondary" type="button" onClick={downloadCalendar}><Download size={16} />Скачать платёжный календарь (CSV)</button><span className="tag">{horizon} дней</span></div></div><BalanceChart points={items} history={result.data.history} reserve={reserve} scenarioLabel={scenarioLabel} /><p className="small-note">{result.data.uncertainty_note}</p></section>
      <section className="card chart-card"><div className="card-heading"><div><h2>План-факт</h2><p>Факт по последним операциям; будущий план — базовый прогноз. Исторический план сравнения оценивается по предыдущим одноимённым дням недели.</p></div><span className="tag good">Автопересчёт: базовый расчёт переиспользуется из кэша</span></div><PlanFactChart points={items} history={result.data.history} />{overdueEvents.length > 0 && <div className="notice warning-card"><strong>Просроченные платежи: {overdueEvents.length}</strong><span>{overdueEvents.slice(0, 3).map((event) => `${event.description || event.event_type} · ${dateRu(event.date)} · ${currency(event.amount)}`).join(' | ')}</span></div>}</section>
      <section className="card chart-card"><div className="card-heading"><div><h2>Динамика чистого потока по дням</h2><p>Поступления, списания и итоговый чистый поток, ₽</p></div></div><NetCashFlowChart points={items} /></section>
      {active && <section className="notice scenario-comparison"><ShieldAlert size={18} /><span>Минимальный остаток: базовый {currency(baseMinimum)} · сценарный {currency(scenarioMinimum)}. {scenarioBreaksEarlier ? `Сценарный разрыв наступит раньше: ${dateRu(scenarioBreakDate)}.` : 'Сценарий не переносит разрыв на более раннюю дату.'}</span></section>}
      <div className="metrics-grid">
        <article className="metric-card"><div className="metric-icon amber"><CalendarDays size={19} /></div><div className="metric-title">Риск нарушения резерва</div><div className="metric-value">{result.data.risk.risk_level}</div><div className="metric-detail">вероятность: {percent(result.data.risk.probability)}</div></article>
      </div>
      {result.data.warning ? <section className="card warning-card"><div className="warning-heading"><AlertTriangle size={20} /><h2>Возможное снижение остатка ниже резерва</h2></div><p><strong>{dateRu(result.data.warning.date)}</strong> — прогнозная нехватка {currency(result.data.warning.deficit)}. {result.data.warning.reasons}</p><p>{result.data.warning.action}</p><p className="small-note">Риск рассчитан методом: {result.data.risk.method}</p></section> : <div className="notice"><ShieldAlert size={17} /> Детерминированный прогноз не показывает пересечения выбранного резерва.</div>}
      <CalculationTrace trace={result.data.calculation_trace} />
    </>}</QueryState>
  </div>
}
