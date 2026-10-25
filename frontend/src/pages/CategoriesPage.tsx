import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { QueryState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys } from '../hooks/queries'
import { currency } from '../utils/format'

const COLORS = ['#268a68','#5588d2','#e3a53b','#d77872','#8b74cd','#54a5b0','#d68fba','#6c86a1']

export function CategoriesPage() {
  const { company } = useCompanyContext()
  const companyId = company?.company_id
  const result = useQuery({ queryKey: keys.categories(companyId ?? ''), queryFn: () => api.categories(companyId ?? ''), enabled: Boolean(companyId) })
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">СТРУКТУРА ДВИЖЕНИЯ ДЕНЕГ</div><h1>Категории</h1><p>Распределение по суммам операций; доля считается отдельно для поступлений и списаний.</p></div></div>
    <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{result.data && <div className="content-grid">
      {(['поступление', 'списание'] as const).map((direction) => {
        const rows = result.data.by_direction[direction] ?? []
        const total = rows.reduce((sum, row) => sum + row.amount, 0)
        return <section className="card category-card" key={direction}><div className="card-heading"><div><h2>{direction === 'поступление' ? 'Поступления' : 'Расходы'}</h2><p>Итого {currency(total)}</p></div></div>
          {!rows.length ? <div className="empty-state">Нет операций для распределения.</div> : <><div className="category-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={rows} dataKey="amount" nameKey="category" innerRadius={62} outerRadius={96} paddingAngle={2}>{rows.map((row, index) => <Cell key={row.category} fill={COLORS[index % COLORS.length]} />)}</Pie><Tooltip formatter={(value) => currency(Number(value))} /><Legend /></PieChart></ResponsiveContainer></div>
            <div className="category-list">{rows.map((row, index) => <div className="category-row" key={row.category}><span className="category-color" style={{ backgroundColor: COLORS[index % COLORS.length] }} /><span>{row.category}<small>{row.operations} операций</small></span><strong>{currency(row.amount)}<small>{(row.share * 100).toFixed(1)}%</small></strong></div>)}</div></>}
        </section>
      })}
    </div>}</QueryState>
    {result.data?.monthly.length ? <section className="card chart-card"><div className="card-heading"><div><h2>Динамика потоков по месяцам</h2><p>Суммы по месяцам, отдельно для поступлений и расходов.</p></div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><BarChart data={Object.values(result.data.monthly.reduce<Record<string, { month: string; поступление: number; списание: number }>>((acc, row) => { acc[row.month] ??= { month: row.month, поступление: 0, списание: 0 }; acc[row.month][row.direction as 'поступление' | 'списание'] += row.flow_amount; return acc }, {}))}><CartesianGrid stroke="#edf0f5" vertical={false} /><XAxis dataKey="month" /><YAxis tickFormatter={(value) => `${Math.round(value / 1000)} тыс.`} /><Tooltip formatter={(value) => currency(Number(value))} /><Legend /><Bar dataKey="поступление" fill="#288968" radius={[4, 4, 0, 0]} /><Bar dataKey="списание" fill="#d27a73" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div></section> : null}
  </div>
}
