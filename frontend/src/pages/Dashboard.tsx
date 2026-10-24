import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CalendarClock, CircleDollarSign, CreditCard, ShieldCheck, TrendingUp, TriangleAlert, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { BalanceChart } from '../components/dashboard/BalanceChart'
import { MetricCard } from '../components/dashboard/MetricCard'
import { QueryState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys, useForecast, useSummary } from '../hooks/queries'
import { currency, dateRu, percent } from '../utils/format'

export function Dashboard() {
  const { company, dataAvailable } = useCompanyContext()
  const id = company?.company_id
  const summary = useSummary(id, 90, 0)
  const forecast = useForecast(id, 90, 0)
  const events = useQuery({ queryKey: keys.events(id ?? ''), queryFn: () => api.events(id!), enabled: Boolean(id) })

  if (!dataAvailable) return <section className="card empty-dataset">
    <div className="empty-dataset-icon"><Wallet size={28} /></div>
    <h2>Подключите датасет компаний</h2>
    <p>В текущей папке проекта нет файлов исходного набора. API работает, но реальные финансовые показатели не подставляются вместо него.</p>
    <p>Поместите распакованные файлы в <code>data/dataset/</code>: <code>companies.csv</code> и <code>all_operations.csv</code> либо каталог <code>statements/</code>.</p>
    <Link className="button secondary" to="/companies">Проверить список компаний <ArrowRight size={16} /></Link>
  </section>

  return <div className="page-stack">
    <div className="page-heading"><div><div className="eyebrow">ФИНАНСОВАЯ ПАНЕЛЬ</div><h1>{company?.name ?? 'Обзор компании'}</h1><p>{company?.industry ?? 'Выберите компанию'} · {company?.legal_form ?? ''}</p></div><span className="tag good"><span />Данные компании</span></div>
    <QueryState isLoading={summary.isLoading || forecast.isLoading} error={(summary.error ?? forecast.error) as Error | null}>
      {summary.data && forecast.data && <>
        {!summary.data.balance_is_current && <div className="notice"><CalendarClock size={17} /> Остаток из выписки актуален на {dateRu(summary.data.balance_date)} — это последний доступный фактический остаток, не баланс на сегодня.</div>}
        {(summary.data.needs_review_count ?? 0) > 0 && <div className="notice"><TriangleAlert size={18} /> <span>Обнаружено {summary.data.needs_review_count} неопределённых платежей, которые не удалось распределить автоматически. Отметьте их категорию вручную — система запомнит ваш выбор</span> <Link className="text-link" to="/operations?category=Требует+проверки">Перейти к разметке <ArrowRight size={15} /></Link></div>}
        <div className="metrics-grid">
          <MetricCard title="Последний остаток" value={currency(summary.data.last_balance)} detail={dateRu(summary.data.balance_date)} icon={Wallet} tone="mint" />
          <MetricCard title="Прогноз через 30 дней" value={currency(summary.data.forecast_balance_30)} detail="по базовому сценарию" icon={TrendingUp} tone="blue" trend="up" />
          <MetricCard title="Прогноз через 90 дней" value={currency(summary.data.forecast_balance_90)} detail={summary.data.selected_model} icon={CircleDollarSign} tone="amber" />
          <MetricCard title="Предстоящих обязательств" value={summary.data.upcoming_obligations} detail="ожидают или подтверждены" icon={CreditCard} tone="rose" />
        </div>
        <div className="content-grid">
          <section className="card chart-card"><div className="card-heading"><div><h2>Прогноз остатка</h2><p>Исторический backtest выбирает подход на отложенных датах</p></div><Link to="/forecast" className="text-link">Подробно <ArrowRight size={15} /></Link></div><BalanceChart points={forecast.data.items} history={forecast.data.history} /></section>
          <section className="card risk-card"><div className="card-heading"><div><h2>Состояние ликвидности</h2><p>Оценка на прогнозном горизонте</p></div><ShieldCheck className="heading-icon" size={20} /></div>
            <div className={`risk-badge ${summary.data.risk_level === 'высокий' ? 'high' : summary.data.risk_level === 'средний' ? 'medium' : 'low'}`}>{summary.data.risk_level}</div>
            <div className="risk-line"><span>Максимальный дефицит</span><strong>{currency(summary.data.max_deficit)}</strong></div>
            <div className="risk-line"><span>Первое нарушение резерва</span><strong>{dateRu(summary.data.first_risk_date)}</strong></div>
            <div className="risk-line"><span>Эмпирическая оценка сценариев</span><strong>{percent(summary.data.risk_probability)}</strong></div>
            <p className="small-note">{forecast.data.risk.method}</p>
          </section>
        </div>
        <div className="metrics-grid lower-metrics">
          <MetricCard title="Поступления, прогноз" value={currency(summary.data.forecast_inflows)} detail="на выбранный горизонт" icon={TrendingUp} tone="mint" />
          <MetricCard title="Расходы, прогноз" value={currency(summary.data.forecast_outflows)} detail="без суммы будущих событий" icon={CreditCard} tone="rose" />
          <MetricCard title="Дней в истории" value={summary.data.history_days} detail={`${summary.data.observed_days} дней с операциями`} icon={CalendarClock} tone="blue" />
          <MetricCard title="Пропуски в истории" value={summary.data.unobserved_calendar_days} detail={`${summary.data.balance_consistency_errors} проверок остатков требуют внимания`} icon={ShieldCheck} tone="amber" />
        </div>
        <div className="card-heading section-heading"><div><h2>Ближайшие события</h2><p>Сохранённые обязательства компании</p></div><Link to="/events" className="text-link">Все события <ArrowRight size={15} /></Link></div>
        <div className="card event-preview">{events.data?.items.filter((item) => item.status !== 'Отменено').slice(0, 4).map((event) => <div className="event-row" key={event.id}><span className={`event-dot ${event.direction === 'поступление' ? 'income' : 'expense'}`} /><div><strong>{event.description || event.event_type}</strong><small>{dateRu(event.date)} · {event.category}</small></div><b className={event.direction === 'поступление' ? 'positive' : 'negative'}>{currency(event.direction === 'поступление' ? event.amount : -event.amount)}</b></div>) ?? <div className="empty-state">Будущих событий пока нет.</div>}</div>
      </>}
    </QueryState>
  </div>
}
