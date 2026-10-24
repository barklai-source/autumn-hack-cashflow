import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, SlidersHorizontal, TriangleAlert } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { QueryState, EmptyState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys } from '../hooks/queries'
import { currency, dateRu } from '../utils/format'

const CATEGORIES = ['Выручка и поступления от клиентов','Закупки и поставщики','Фонд оплаты труда','Налоги и обязательные платежи','Аренда','Маркетинг и реклама','Логистика и транспорт','Комиссии банка','Кредиты и проценты','Лизинг','Оборудование и капитальные расходы','Переводы между собственными счетами','Прочие поступления','Прочие расходы','Требует проверки']

export function OperationsPage() {
  const { company } = useCompanyContext()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [direction, setDirection] = useState('')
  const [category, setCategory] = useState(() => searchParams.get('category') ?? '')
  const [counterparty, setCounterparty] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const params = new URLSearchParams({ page: String(page), page_size: '30', sort: 'operation_date', order: sortOrder })
  if (search) params.set('search', search)
  if (direction) params.set('direction', direction)
  if (category) params.set('category', category)
  if (counterparty) params.set('counterparty', counterparty)
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const queryKey = params.toString()
  const result = useQuery({ queryKey: keys.operations(company?.company_id ?? '', queryKey), queryFn: () => api.operations(company!.company_id, params) })
  const categoryChange = useMutation({
    mutationFn: ({ operationId, value }: { operationId: string; value: string }) => api.changeCategory(company!.company_id, operationId, value),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operations', company?.company_id] }),
        queryClient.invalidateQueries({ queryKey: ['summary', company?.company_id] }),
        queryClient.invalidateQueries({ queryKey: ['categories', company?.company_id] }),
        queryClient.invalidateQueries({ queryKey: ['recurring', company?.company_id] }),
      ])
    },
  })
  const pageCount = Math.ceil((result.data?.total ?? 0) / 30)
  const setFilter = (action: () => void) => { action(); setPage(1) }
  const selectCategory = (value: string) => {
    setCategory(value)
    const next = new URLSearchParams(searchParams)
    if (value) next.set('category', value)
    else next.delete('category')
    setSearchParams(next, { replace: true })
  }
  return <div className="page-stack">
    <div className="page-heading"><div><div className="eyebrow">ИСТОРИЯ КОМПАНИИ</div><h1>Операции</h1><p>Постраничная загрузка с сервера. Корректировки категорий сохраняются в SQLite.</p></div><span className="tag">{result.data?.total.toLocaleString('ru-RU') ?? '…'} операций</span></div>
    <section className="card">
      {(result.data?.needs_review_count ?? 0) > 0 && <div className="notice"><TriangleAlert size={17} /> <span>Есть операции, требующие ручной проверки.</span><button className="button secondary" onClick={() => { selectCategory('Требует проверки'); setPage(1) }}>Показать требующие проверки ({result.data?.needs_review_count})</button></div>}
      <div className="operation-filters">
        <label className="search-box"><Search size={17} /><input placeholder="Поиск: контрагент или назначение" value={search} onChange={(event) => setFilter(() => setSearch(event.target.value))} /></label>
        <label><SlidersHorizontal size={15} /><select aria-label="Направление" value={direction} onChange={(event) => setFilter(() => setDirection(event.target.value))}><option value="">Все направления</option><option value="поступление">Поступления</option><option value="списание">Списания</option></select></label>
        <label><select aria-label="Категория" value={category} onChange={(event) => setFilter(() => selectCategory(event.target.value))}><option value="">Все категории</option>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label>
        <input aria-label="Контрагент" placeholder="Контрагент" value={counterparty} onChange={(event) => setFilter(() => setCounterparty(event.target.value))} />
        <input aria-label="Дата с" type="date" value={startDate} onChange={(event) => setFilter(() => setStartDate(event.target.value))} />
        <input aria-label="Дата по" type="date" value={endDate} onChange={(event) => setFilter(() => setEndDate(event.target.value))} />
        <button className="button secondary" onClick={() => { setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc'); setPage(1) }}>Дата {sortOrder === 'desc' ? '↓' : '↑'}</button>
      </div>
      <QueryState isLoading={result.isLoading} error={result.error as Error | null}>
        {result.data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Дата</th><th>Контрагент / назначение</th><th>Направление</th><th>Сумма</th><th>Остаток дня</th><th>Категория</th></tr></thead><tbody>{result.data.items.map((operation) => <tr key={operation.operation_id}>
          <td className="nowrap">{dateRu(operation.operation_date)}</td><td><strong>{operation.counterparty_name || 'Не указан'}</strong><small className="table-subtitle">{operation.payment_purpose || '—'}</small><small className="table-subtitle">ИНН: {operation.counterparty_inn || '—'}</small></td>
          <td><span className={`direction-tag ${operation.direction === 'поступление' ? 'income' : 'expense'}`}>{operation.direction}</span></td><td className={operation.signed_amount > 0 ? 'positive nowrap' : 'negative nowrap'}>{currency(operation.signed_amount)}</td><td className="nowrap">{currency(operation.balance_eod)}</td><td><select className="category-select" aria-label={`Категория ${operation.operation_id}`} value={operation.category} onChange={(event) => categoryChange.mutate({ operationId: operation.operation_id, value: event.target.value })}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select>{operation.needs_review && <small className="review-note">Проверьте вручную</small>}</td>
        </tr>)}</tbody></table></div> : <EmptyState>По этим фильтрам операций нет.</EmptyState>}
      </QueryState>
      <div className="pagination"><span>Страница {page} из {Math.max(pageCount, 1)} · всего {result.data?.total ?? 0}</span><div><button className="button secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Назад</button><button className="button secondary" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>Далее</button></div></div>
      {categoryChange.isError && <p className="inline-error">{categoryChange.error.message}</p>}
    </section>
  </div>
}
