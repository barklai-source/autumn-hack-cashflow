import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Repeat2 } from 'lucide-react'
import { api } from '../api/client'
import { QueryState, EmptyState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys } from '../hooks/queries'
import { currency, dateRu, percent } from '../utils/format'

export function RecurringPage() {
  const { company } = useCompanyContext()
  const companyId = company?.company_id
  const client = useQueryClient()
  const result = useQuery({ queryKey: keys.recurring(companyId ?? ''), queryFn: () => api.recurring(companyId ?? ''), enabled: Boolean(companyId) })
  const mutation = useMutation({ mutationFn: ({ id, confirmed }: { id: string; confirmed: boolean }) => {
    if (!companyId) throw new Error('Сначала выберите компанию.')
    return api.confirmRecurring(companyId, id, confirmed)
  }, onSuccess: () => client.invalidateQueries({ queryKey: keys.recurring(companyId ?? '') }) })
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">ПОВТОРЯЮЩИЕСЯ ДЕНЕЖНЫЕ ПОТОКИ</div><h1>Регулярные операции</h1><p>Стабильные регулярные серии автоматически включаются в прогноз. Вы можете исключить ненужные вручную</p></div></div>
    <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{!result.data?.items.length ? <div className="card"><EmptyState>Подходящих устойчивых серий не найдено.</EmptyState></div> : <div className="card"><div className="table-scroll"><table><thead><tr><th>Контрагент / направление</th><th>Периодичность</th><th>Типичная сумма</th><th>Следующая дата</th><th>Наблюдений</th><th>Надёжность*</th><th>Решение</th></tr></thead><tbody>{result.data.items.map((item) => { const autoIncluded = item.confidence >= 0.75 && item.confirmed; return <tr key={item.recurring_id}><td><strong>{item.counterparty || item.category}</strong><small className="table-subtitle">{item.category} · {item.direction}</small></td><td><span className="direction-tag neutral"><Repeat2 size={13} />{item.frequency}</span></td><td className={item.amount > 0 ? 'positive' : 'negative'}>{currency(item.amount)}</td><td>{dateRu(item.next_date)}</td><td>{item.observations}</td><td>{percent(item.confidence)}</td><td className="recurring-decision">{autoIncluded && <span className="recurring-auto-badge">Авто-включено в прогноз</span>}<button className={`button ${item.confirmed ? 'secondary' : 'primary'}`} disabled={mutation.isPending} onClick={() => mutation.mutate({ id: item.recurring_id, confirmed: !item.confirmed })}>{item.confirmed ? 'Исключить из прогноза' : 'Включить в прогноз'}</button></td></tr> })}</tbody></table></div><p className="small-note">* Оценка серии по устойчивости интервалов и суммы, не статистическая вероятность будущего платежа.</p></div>}</QueryState>
  </div>
}
