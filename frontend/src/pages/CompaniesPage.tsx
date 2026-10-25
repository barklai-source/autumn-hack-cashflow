import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Search, Upload } from 'lucide-react'
import { useMemo, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { QueryState, EmptyState } from '../components/State'
import { keys } from '../hooks/queries'
import { currency, dateRu } from '../utils/format'

export function CompaniesPage() {
  const [search, setSearch] = useState('')
  const [industry, setIndustry] = useState('')
  const [legalForm, setLegalForm] = useState('')
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [companiesFile, setCompaniesFile] = useState<File | null>(null)
  const [operationsFile, setOperationsFile] = useState<File | null>(null)
  const [datasetChoice, setDatasetChoice] = useState('default')
  const [customDatasetPath, setCustomDatasetPath] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const health = useQuery({ queryKey: keys.health, queryFn: api.health })
  const result = useQuery({ queryKey: keys.overview, queryFn: api.overview })
  const reload = useMutation({
    mutationFn: api.reloadDataset,
    onSuccess: async () => {
      await queryClient.invalidateQueries()
    },
  })
  const invalidateDatasetQueries = async () => {
    await queryClient.invalidateQueries()
    await health.refetch()
  }
  const upload = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: async () => {
      setZipFile(null)
      setCompaniesFile(null)
      setOperationsFile(null)
      await invalidateDatasetQueries()
    },
  })
  const switchDataset = useMutation({
    mutationFn: api.switchDataset,
    onSuccess: invalidateDatasetQueries,
  })
  const acceptDroppedFiles = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const files = Array.from(event.dataTransfer.files)
    const zip = files.find((file) => file.name.toLowerCase().endsWith('.zip'))
    if (zip) {
      setZipFile(zip)
      setCompaniesFile(null)
      setOperationsFile(null)
      return
    }
    const companiesCsv = files.find((file) => file.name.toLowerCase() === 'companies.csv')
    const operationsCsv = files.find((file) => file.name.toLowerCase() === 'all_operations.csv')
    if (companiesCsv) setCompaniesFile(companiesCsv)
    if (operationsCsv) setOperationsFile(operationsCsv)
  }
  const industries = useMemo(() => [...new Set((result.data?.rows ?? []).map((row) => row.industry).filter(Boolean))].sort(), [result.data])
  const legalForms = useMemo(() => [...new Set((result.data?.rows ?? []).map((row) => row.legal_form).filter(Boolean))].sort(), [result.data])
  const rows = (result.data?.rows ?? []).filter((row) =>
    (!search || `${row.company_id} ${row.name} ${row.inn}`.toLowerCase().includes(search.toLowerCase())) &&
    (!industry || row.industry === industry) && (!legalForm || row.legal_form === legalForm),
  )
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">КОМПАНИИ И ДАТАСЕТ</div><h1>Все компании</h1><p>{result.data ? `${result.data.companies} компаний · ${result.data.operations.toLocaleString('ru-RU')} операций` : 'Выберите компанию, чтобы перейти к её аналитике.'}</p></div><button className="button secondary" type="button" disabled={reload.isPending} onClick={() => reload.mutate()}><Database size={16} />{reload.isPending ? 'Обновление…' : 'Обновить данные датасета'}</button></div>
    {reload.isSuccess && <div className="notice success-notice">Датасет обновлён: загружено компаний {reload.data.total}.</div>}
    {reload.isError && <div className="inline-error">{reload.error.message}</div>}
    <section className="card dataset-management">
      <div className="card-heading"><div><h2>Управление датасетом</h2><p>Текущий статус: {health.isLoading ? 'загрузка…' : `${health.data?.companies ?? 0} компаний · ${(health.data?.operations ?? 0).toLocaleString('ru-RU')} операций`}</p></div><Database size={19} /></div>
      <div className="dataset-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={acceptDroppedFiles}>
        <Upload size={20} />
        <strong>Перетащите ZIP или оба CSV-файла сюда</strong>
        <span>{zipFile?.name ?? `${companiesFile?.name ?? 'companies.csv не выбран'} · ${operationsFile?.name ?? 'all_operations.csv не выбран'}`}</span>
        <label className="button secondary">Выбрать ZIP<input type="file" accept=".zip,application/zip" onChange={(event) => { const file = event.target.files?.[0] ?? null; setZipFile(file); setCompaniesFile(null); setOperationsFile(null); event.currentTarget.value = '' }} /></label>
      </div>
      <div className="dataset-file-pickers">
        <label>companies.csv<input type="file" accept=".csv,text/csv" onChange={(event) => { setCompaniesFile(event.target.files?.[0] ?? null); setZipFile(null); event.currentTarget.value = '' }} /></label>
        <label>all_operations.csv<input type="file" accept=".csv,text/csv" onChange={(event) => { setOperationsFile(event.target.files?.[0] ?? null); setZipFile(null); event.currentTarget.value = '' }} /></label>
        <button className="button primary" type="button" disabled={upload.isPending || (!zipFile && (!companiesFile || !operationsFile))} onClick={() => upload.mutate({ zip: zipFile ?? undefined, companies: companiesFile ?? undefined, operations: operationsFile ?? undefined })}>{upload.isPending ? 'Загружаем и проверяем…' : 'Загрузить и переключить'}</button>
      </div>
      <div className="dataset-switcher">
        <label>Быстрый датасет<select value={datasetChoice} onChange={(event) => setDatasetChoice(event.target.value)}><option value="default">Основной датасет</option><option value="preloaded_test">Защита / Жюри</option><option value="custom">Путь к папке…</option></select></label>
        {datasetChoice === 'custom' && <label>Путь к директории на сервере<input value={customDatasetPath} onChange={(event) => setCustomDatasetPath(event.target.value)} placeholder="/path/to/dataset" /></label>}
        <button className="button secondary" type="button" disabled={switchDataset.isPending || (datasetChoice === 'custom' && !customDatasetPath.trim())} onClick={() => switchDataset.mutate(datasetChoice === 'custom' ? customDatasetPath.trim() : datasetChoice)}>{switchDataset.isPending ? 'Переключаем…' : 'Применить за 1 клик'}</button>
      </div>
      {(upload.isSuccess || switchDataset.isSuccess) && <div className="notice success-notice">Датасет успешно обновлен. Актуальный статус показан выше.</div>}
      {(upload.isError || switchDataset.isError) && <div className="inline-error">{upload.error?.message ?? switchDataset.error?.message}</div>}
    </section>
    <section className="card"><div className="operation-filters"><label className="search-box"><Search size={16} /><input placeholder="Поиск по ID, названию или ИНН" value={search} onChange={(event) => setSearch(event.target.value)} /></label><select aria-label="Фильтр отрасли" value={industry} onChange={(event) => setIndustry(event.target.value)}><option value="">Все виды деятельности</option>{industries.map((item) => <option key={item}>{item}</option>)}</select><select aria-label="Фильтр организационной формы" value={legalForm} onChange={(event) => setLegalForm(event.target.value)}><option value="">Все ОПФ</option>{legalForms.map((item) => <option key={item}>{item}</option>)}</select></div>
      <QueryState isLoading={result.isLoading} error={result.error as Error | null}>{rows.length ? <div className="table-scroll"><table><thead><tr><th>Компания</th><th>ИНН</th><th>Деятельность</th><th>ОПФ</th><th>Период истории</th><th>Операции</th><th>Последний остаток</th><th></th></tr></thead><tbody>{rows.map((row) => <tr key={row.company_id}><td><strong>{row.name}</strong><small className="table-subtitle">{row.company_id}</small></td><td>{row.inn || '—'}</td><td>{row.industry || '—'}</td><td>{row.legal_form || '—'}</td><td>{dateRu(row.first_operation_date)} — {dateRu(row.last_operation_date)}</td><td>{row.operation_count ?? 0}</td><td>{currency(row.last_balance)}<small className="table-subtitle">{dateRu(row.balance_date)}</small></td><td><button className="button secondary" onClick={() => { localStorage.setItem('selected-company', row.company_id); window.dispatchEvent(new CustomEvent('cashflow-company-selected', { detail: row.company_id })); navigate('/') }}>Открыть</button></td></tr>)}</tbody></table></div> : <EmptyState>{result.data ? 'Нет компаний по этим фильтрам.' : 'Справочник компаний ещё не подключён.'}</EmptyState>}</QueryState>
    </section>
  </div>
}
