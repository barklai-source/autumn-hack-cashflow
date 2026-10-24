import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowDownRight, ArrowUpRight, Sparkles } from 'lucide-react'
import { api } from '../api/client'
import { QueryState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys } from '../hooks/queries'
import { currency } from '../utils/format'

export function QualityPage() {
  const { company } = useCompanyContext()
  const result = useQuery({ queryKey: keys.evaluation(company?.company_id ?? ''), queryFn: () => api.evaluation(company!.company_id), enabled: Boolean(company) })
  const baseline = result.data?.metrics.find((row) => String(row.method).toLowerCase() === 'baseline')
  const ml = result.data?.metrics.find((row) => String(row.method).toLowerCase() === 'ml')
  const improvement = (metric: 'MAE' | 'WAPE') => {
    const baselineValue = baseline?.[metric]
    const mlValue = ml?.[metric]
    if (typeof baselineValue !== 'number' || typeof mlValue !== 'number' || !Number.isFinite(baselineValue)
      || !Number.isFinite(mlValue) || baselineValue <= 0) return null
    return ((baselineValue - mlValue) / baselineValue) * 100
  }
  const maeGain = improvement('MAE')
  const wapeGain = improvement('WAPE')
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">ОТЛОЖЕННАЯ ИСТОРИЧЕСКАЯ ПРОВЕРКА</div><h1>Качество модели</h1><p>Временное разделение: прогноз каждой контрольной точки строится только на прошлом.</p></div></div>
    <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{result.data && <>
      <div className="notice"><strong>Выбранный метод: {result.data.selected_method}.</strong> Оцениваются потоки, а не гарантированная точность будущего остатка. Показатели относятся к конкретной выбранной компании.</div>
      <section className="card ml-advantage-card"><div className="ml-advantage-heading"><span className="metric-icon green"><Sparkles size={19} /></span><div><h2>Преимущество ML-ансамбля над Baseline</h2><p>Снижение ошибки относительно наивного сезонного среднего по данным walk-forward.</p></div></div><div className="ml-advantage-metrics">{([
        ['MAE', maeGain],
        ['WAPE', wapeGain],
      ] as const).map(([label, value]) => <div className="ml-advantage-metric" key={label}><span>{label}</span><strong className={value === null ? '' : value >= 0 ? 'positive' : 'negative'}>{value === null ? 'Недостаточно данных' : <>{value >= 0 ? <ArrowDownRight size={17} /> : <ArrowUpRight size={17} />}{value > 0 ? '+' : ''}{value.toFixed(1)}%</>}</strong><small>{value === null ? 'Сравнение недоступно' : value >= 0 ? 'меньше ошибка ML' : 'ошибка ML выше Baseline'}</small></div>)}</div></section>
      <section className="card"><div className="card-heading"><div><h2>Сравнение подходов</h2><p>MAE и RMSE — в рублях; WAPE — сумма ошибки к сумме факта.</p></div></div>
        {result.data.metrics.length ? <div className="table-scroll"><table><thead><tr>{Object.keys(result.data.metrics[0]).map((field) => <th key={field}>{field}</th>)}</tr></thead><tbody>{result.data.metrics.map((row, index) => <tr key={index}>{Object.entries(row).map(([field, value]) => <td key={field}>{typeof value === 'number' ? field.toLowerCase().includes('wape') ? `${(value * 100).toFixed(1)}%` : currency(value) : value ?? '—'}</td>)}</tr>)}</tbody></table></div> : <div className="empty-state">Недостаточно истории для walk-forward-сравнения двух моделей.</div>}
      </section>
      <section className="card"><div className="card-heading"><div><h2>Ошибка прогноза остатка по горизонтам</h2><p>7, 30 и 90 дней от каждой временной точки отсечения.</p></div></div>{result.data.balance_horizons.length ? <div className="table-scroll"><table><thead><tr>{Object.keys(result.data.balance_horizons[0]).map((field) => <th key={field}>{field}</th>)}</tr></thead><tbody>{result.data.balance_horizons.map((row, index) => <tr key={index}>{Object.entries(row).map(([field, value]) => <td key={field}>{typeof value === 'number' ? field.toLowerCase().includes('wape') ? `${(value * 100).toFixed(1)}%` : currency(value) : value ?? '—'}</td>)}</tr>)}</tbody></table></div> : <div className="empty-state">Для оценки остатка нужен достаточный исторический период.</div>}</section>
      {result.data.backtest.length > 0 && <section className="card chart-card"><div className="card-heading"><div><h2>Фактические и исторические прогнозы</h2><p>Контрольные даты walk-forward-теста</p></div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><LineChart data={result.data.backtest}><CartesianGrid stroke="#edf0f5" vertical={false} /><XAxis dataKey="date" tickFormatter={(value) => new Date(value).toLocaleDateString('ru-RU')} minTickGap={32} /><YAxis tickFormatter={(value) => `${Math.round(value / 1000)} тыс.`} /><Tooltip formatter={(value) => currency(Number(value))} /><Legend /><Line dataKey="actual_net" name="Фактический поток" stroke="#3376c2" dot={false} /><Line dataKey="ML" name="Прогноз HistGradientBoosting" stroke="#35a27b" dot={false} /><Line dataKey="baseline" name="Базовый прогноз" stroke="#d69b38" dot={false} /></LineChart></ResponsiveContainer></div></section>}
      <div className="small-note">Метрики и вероятностные оценки — эмпирические. Изменение бизнеса и структурные сдвиги могут ухудшить качество прогнозирования.</div>
    </>}</QueryState>
  </div>
}
