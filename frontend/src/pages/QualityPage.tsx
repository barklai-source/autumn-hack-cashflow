import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowDownRight, ArrowUpRight, Sparkles } from 'lucide-react'
import { api } from '../api/client'
import { CalculationTrace } from '../components/CalculationTrace'
import { QueryState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys } from '../hooks/queries'
import { currency } from '../utils/format'

const metricLabels = [
  ['MAE', 'MAE остатка'],
  ['MSE', 'MSE остатка'],
  ['RMSE', 'RMSE остатка'],
  ['MAPE', 'MAPE остатка'],
  ['R2', 'R²'],
  ['Accuracy', 'Accuracy разрыва'],
  ['Precision', 'Precision разрыва'],
  ['Recall', 'Recall разрыва'],
  ['F1', 'F1-score разрыва'],
  ['ROC_AUC', 'ROC-AUC разрыва'],
] as const

function metricValue(value: number | null | undefined, percentage = false) {
  if (value == null || !Number.isFinite(value)) return 'Н/Д'
  return percentage ? `${(value * 100).toFixed(1)}%` : value.toLocaleString('ru-RU', { maximumFractionDigits: 3 })
}

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
  const quality = result.data?.quality_metrics
  const hybrid = quality?.comparison.find((row) => row.method.startsWith('Гибридный ансамбль'))
  const confusion = quality?.cash_gap_confusion
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">ОТЛОЖЕННАЯ ИСТОРИЧЕСКАЯ ПРОВЕРКА</div><h1>Качество модели</h1><p>Временное разделение: прогноз каждой контрольной точки строится только на прошлом.</p></div></div>
    <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{result.data && <>
      <div className="notice"><strong>Выбранный метод: {result.data.selected_method}.</strong> Оцениваются потоки, а не гарантированная точность будущего остатка. Показатели относятся к конкретной выбранной компании.</div>
      <div className="notice quality-split">Train/test: {quality?.train_test.train_days ?? 0} / {quality?.train_test.test_days ?? 0} дней · граница теста: {quality?.train_test.split_date ?? 'недостаточно данных'} · метрики остатка рассчитаны для накопленного баланса на holdout-периоде.</div>
      {hybrid && <section className="card quality-metric-section"><div className="card-heading"><div><h2>Метрики на отложенной выборке</h2><p>Выбранный ансамбль · регрессия остатка и классификация кассового разрыва</p></div></div><div className="quality-metrics-grid">{metricLabels.map(([key, label]) => <article className="quality-metric" key={key}><span>{label}</span><strong>{metricValue(key === 'MAPE' && hybrid[key] !== null ? hybrid[key] / 100 : hybrid[key], key === 'MAPE')}</strong></article>)}<article className="quality-metric"><span>Bootstrap вероятность разрыва</span><strong>{metricValue(confusion?.forecast_risk_probability, true)}</strong></article></div></section>}
      <section className="card ml-advantage-card"><div className="ml-advantage-heading"><span className="metric-icon green"><Sparkles size={19} /></span><div><h2>Преимущество ML-ансамбля над Baseline</h2><p>Снижение ошибки относительно наивного сезонного среднего по данным walk-forward.</p></div></div><div className="ml-advantage-metrics">{([
        ['MAE', maeGain],
        ['WAPE', wapeGain],
      ] as const).map(([label, value]) => <div className="ml-advantage-metric" key={label}><span>{label}</span><strong className={value === null ? '' : value >= 0 ? 'positive' : 'negative'}>{value === null ? 'Недостаточно данных' : <>{value >= 0 ? <ArrowDownRight size={17} /> : <ArrowUpRight size={17} />}{value > 0 ? '+' : ''}{value.toFixed(1)}%</>}</strong><small>{value === null ? 'Сравнение недоступно' : value >= 0 ? 'меньше ошибка ML' : 'ошибка ML выше Baseline'}</small></div>)}</div></section>
      <section className="card"><div className="card-heading"><div><h2>Сравнение подходов</h2><p>Метрики регрессии остатка и классификации разрывов на общей хронологической holdout-выборке.</p></div></div>
        {quality?.comparison.length ? <div className="table-scroll"><table><thead><tr><th>Подход</th><th>MAE, ₽</th><th>MSE</th><th>RMSE, ₽</th><th>MAPE</th><th>R²</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th></tr></thead><tbody>{quality.comparison.map((row) => <tr key={row.method}><th>{row.method}</th><td>{metricValue(row.MAE)}</td><td>{metricValue(row.MSE)}</td><td>{metricValue(row.RMSE)}</td><td>{row.MAPE === null ? 'Н/Д' : `${metricValue(row.MAPE)}%`}</td><td>{metricValue(row.R2)}</td><td>{metricValue(row.Accuracy, true)}</td><td>{metricValue(row.Precision, true)}</td><td>{metricValue(row.Recall, true)}</td><td>{metricValue(row.F1, true)}</td><td>{metricValue(row.ROC_AUC, true)}</td></tr>)}</tbody></table></div> : <div className="empty-state">Для train/test-сравнения нужно больше исторических данных.</div>}
      </section>
      <section className="card"><div className="card-heading"><div><h2>Матрица ошибок кассовых разрывов (2×2)</h2><p>Факт по тестовому остатку ниже нуля · классификация гибридного прогноза</p></div></div>
        {confusion && confusion.sample_count > 0 ? <><div className="table-scroll"><table className="confusion-matrix"><thead><tr><th>Факт \ прогноз</th><th>Разрыв</th><th>Нет разрыва</th></tr></thead><tbody>
          <tr><th>Разрыв</th><td className="confusion-positive"><strong>TP {confusion.TP}</strong><span>{confusion.percentages.TP.toFixed(1)}%</span></td><td className="confusion-error"><strong>FN {confusion.FN}</strong><span>{confusion.percentages.FN.toFixed(1)}%</span></td></tr>
          <tr><th>Нет разрыва</th><td className="confusion-error"><strong>FP {confusion.FP}</strong><span>{confusion.percentages.FP.toFixed(1)}%</span></td><td className="confusion-negative"><strong>TN {confusion.TN}</strong><span>{confusion.percentages.TN.toFixed(1)}%</span></td></tr>
        </tbody></table></div><p className="small-note">Выборка: {confusion.sample_count} дней · ROC-AUC: {metricValue(confusion.roc_auc, true)}</p></> : <div className="empty-state">В тестовом периоде нет достаточного числа фактических случаев для матрицы ошибок.</div>}
      </section>
      {quality?.category_confusion && <section className="card"><div className="card-heading"><div><h2>Матрица категоризации</h2><p>Строки — эталонные правила, столбцы — фактический результат категоризатора. Accuracy: {metricValue(quality.category_confusion.accuracy, true)} · {quality.category_confusion.sample_count} операций</p></div></div><p className="small-note">{quality.category_confusion.reference_note}</p><div className="table-scroll"><table className="category-confusion"><thead><tr><th>Правила \ модель</th>{quality.category_confusion.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{quality.category_confusion.matrix.map((row, index) => <tr key={quality.category_confusion.labels[index]}><th>{quality.category_confusion.labels[index]}</th>{row.map((value, column) => <td key={quality.category_confusion.labels[column]}>{value}</td>)}</tr>)}</tbody></table></div></section>}
      {quality?.diagnostics && <section className="card"><div className="card-heading"><div><h2>Диагностика граничных случаев</h2><p>Пробелы дат, сходимость остатков и выбросы сумм</p></div></div><div className="diagnostic-grid"><article><span>Пропущено календарных дней</span><strong>{quality.diagnostics.missing_calendar_days}</strong></article><article><span>Несходимость дневных остатков</span><strong>{quality.diagnostics.balance_inconsistencies}</strong></article><article><span>Аномалии сумм</span><strong>{quality.diagnostics.anomalies}</strong></article></div><p className="small-note">{quality.diagnostics.anomaly_rule}</p></section>}
      <section className="card architecture-card"><div className="card-heading"><div><h2>Архитектура решения</h2><p>Путь данных от источников до рабочего интерфейса</p></div></div><div className="architecture-flow">{['Источники данных и интеграции', 'Категоризация и регулярные платежи', 'Инкрементальный движок прогноза и What-If', 'FastAPI + RBAC', 'React UI'].map((step, index) => <div className="architecture-node" key={step}><span>{index + 1}</span><strong>{step}</strong>{index < 4 && <b aria-hidden="true">→</b>}</div>)}</div></section>
      <CalculationTrace trace={result.data.calculation_trace} />
      <section className="card"><div className="card-heading"><div><h2>Ошибка прогноза остатка по горизонтам</h2><p>7, 30 и 90 дней от каждой временной точки отсечения.</p></div></div>{result.data.balance_horizons.length ? <div className="table-scroll"><table><thead><tr>{Object.keys(result.data.balance_horizons[0]).map((field) => <th key={field}>{field}</th>)}</tr></thead><tbody>{result.data.balance_horizons.map((row, index) => <tr key={index}>{Object.entries(row).map(([field, value]) => <td key={field}>{typeof value === 'number' ? field.toLowerCase().includes('wape') ? `${(value * 100).toFixed(1)}%` : currency(value) : value ?? '—'}</td>)}</tr>)}</tbody></table></div> : <div className="empty-state">Для оценки остатка нужен достаточный исторический период.</div>}</section>
      {result.data.backtest.length > 0 && <section className="card chart-card"><div className="card-heading"><div><h2>Фактические и исторические прогнозы</h2><p>Контрольные даты walk-forward-теста</p></div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><LineChart data={result.data.backtest}><CartesianGrid stroke="#edf0f5" vertical={false} /><XAxis dataKey="date" tickFormatter={(value) => new Date(value).toLocaleDateString('ru-RU')} minTickGap={32} /><YAxis tickFormatter={(value) => `${Math.round(value / 1000)} тыс.`} /><Tooltip formatter={(value) => currency(Number(value))} /><Legend /><Line dataKey="actual_net" name="Фактический поток" stroke="#3376c2" dot={false} /><Line dataKey="ML" name="Прогноз HistGradientBoosting" stroke="#35a27b" dot={false} /><Line dataKey="baseline" name="Базовый прогноз" stroke="#d69b38" dot={false} /></LineChart></ResponsiveContainer></div></section>}
      <div className="small-note">Метрики и вероятностные оценки — эмпирические. Сверка категорий использует правила как слабую разметку, а не экспертную истину; изменение бизнеса и структурные сдвиги могут ухудшить качество прогноза.</div>
    </>}</QueryState>
  </div>
}
