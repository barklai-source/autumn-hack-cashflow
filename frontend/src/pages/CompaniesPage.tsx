import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { QueryState, EmptyState } from '../components/State'
import { keys } from '../hooks/queries'
import { currency, dateRu } from '../utils/format'

export function CompaniesPage() {
  const [search, setSearch] = useState('')
  const [industry, setIndustry] = useState('')
  const [legalForm, setLegalForm] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const result = useQuery({ queryKey: keys.overview, queryFn: api.overview })
  const reload = useMutation({
    mutationFn: api.reloadDataset,
    onSuccess: async () => {
      await queryClient.invalidateQueries()
    },
  })
  const industries = useMemo(() => [...new Set((result.data?.rows ?? []).map((row) => row.industry).filter(Boolean))].sort(), [result.data])
  const legalForms = useMemo(() => [...new Set((result.data?.rows ?? []).map((row) => row.legal_form).filter(Boolean))].sort(), [result.data])
  const rows = (result.data?.rows ?? []).filter((row) =>
    (!search || `${row.company_id} ${row.name} ${row.inn}`.toLowerCase().includes(search.toLowerCase())) &&
    (!industry || row.industry === industry) && (!legalForm || row.legal_form === legalForm),
  )
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">КОМПАНИИ И ДАТАСЕТ</div><h1>Все компании</h1><p>{result.data ? `${result.data.companies} компаний · ${result.data.operations.toLocaleString('ru-RU')} операций` : 'Выберите компанию, чтобы перейти к её аналитике.'}</p></div><button className="button secondary" type="button" disabled={reload.isPending} onClick={() => reload.mutate()}><Database size={16} />{reload.isPending ? 'Обновление…' : 'Обновить данные датасета'}</button></div>
    {reload.isSuccess && <div className="notice success-notice">Датасет обновлён: загружено компаний {reload.data.total}.</div>}
    {reload.isError && <div className="inline-error">{reload.error.message}</div>}
    <section className="card"><div className="operation-filters"><label className="search-box"><Search size={16} /><input placeholder="Поиск по ID, названию или ИНН" value={search} onChange={(event) => setSearch(event.target.value)} /></label><select aria-label="Фильтр отрасли" value={industry} onChange={(event) => setIndustry(event.target.value)}><option value="">Все виды деятельности</option>{industries.map((item) => <option key={item}>{item}</option>)}</select><select aria-label="Фильтр организационной формы" value={legalForm} onChange={(event) => setLegalForm(event.target.value)}><option value="">Все ОПФ</option>{legalForms.map((item) => <option key={item}>{item}</option>)}</select></div>
      <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{rows.length ? <div className="table-scroll"><table><thead><tr><th>Компания</th><th>ИНН</th><th>Деятельность</th><th>ОПФ</th><th>Период истории</th><th>Операции</th><th>Последний остаток</th><th></th></tr></thead><tbody>{rows.map((row) => <tr key={row.company_id}><td><strong>{row.name}</strong><small className="table-subtitle">{row.company_id}</small></td><td>{row.inn || '—'}</td><td>{row.industry || '—'}</td><td>{row.legal_form || '—'}</td><td>{dateRu(row.first_operation_date)} — {dateRu(row.last_operation_date)}</td><td>{row.operation_count ?? 0}</td><td>{currency(row.last_balance)}<small className="table-subtitle">{dateRu(row.balance_date)}</small></td><td><button className="button secondary" onClick={() => { localStorage.setItem('selected-company', row.company_id); window.dispatchEvent(new CustomEvent('cashflow-company-selected', { detail: row.company_id })); navigate('/') }}>Открыть</button></td></tr>)}</tbody></table></div> : <EmptyState>{result.data ? 'Нет компаний по этим фильтрам.' : 'Справочник компаний ещё не подключён.'}</EmptyState>}</QueryState>
    </section>
  </div>
}
