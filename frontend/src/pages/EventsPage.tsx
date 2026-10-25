import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, FileUp, Pencil, RefreshCw, RotateCcw, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { api } from '../api/client'
import { QueryState, EmptyState } from '../components/State'
import { useCompanyContext } from '../components/CompanyContext'
import { keys, useSummary } from '../hooks/queries'
import { currency, dateRu } from '../utils/format'
import { addDaysToDate, parseEventText } from '../utils/eventTextParser'

const schema = z.object({
  date: z.string().min(1, 'Укажите дату'),
  amount: z.coerce.number().positive('Сумма должна быть больше нуля'),
  direction: z.enum(['поступление', 'списание']),
  category: z.string().min(1),
  event_type: z.string().min(1),
  description: z.string().max(1000),
  counterparty_inn: z.string().max(12).optional(),
  counterparty_name: z.string().max(200).optional(),
  source: z.string().min(1),
  status: z.enum(['Ожидается', 'Подтверждено', 'Исполнено', 'Отменено']),
})
type EventValues = z.output<typeof schema>
type EventFormInput = z.input<typeof schema>

function localToday(): string {
  const today = new Date()
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
}

function sourceBadge(source: string) {
  const normalized = source.toLocaleLowerCase('ru-RU')
  if (normalized.includes('банк') || normalized.includes('кредит') || normalized.includes('зп проект')) {
    return { label: 'Банк (кредит/ЗП проект)', tone: 'bank' }
  }
  if (normalized.includes('фнс') || normalized.includes('налог')) {
    return { label: 'Налоговый календарь ФНС', tone: 'fns' }
  }
  if (normalized.includes('1с') || normalized.includes('эдо') || normalized.includes('счёт') || normalized.includes('счет') || normalized.includes('erp')) {
    return { label: '1С / ЭДО (договоры и счета)', tone: 'one-c' }
  }
  return { label: 'Ручной ввод предпринимателя', tone: 'nlp' }
}

const NLP_EXAMPLES = [
  'Клиент оплатит 350000 через 15 дней по договору',
  'Оплата аренды офиса 120 000 завтра',
  'Налоговый платёж 250 тыс через 7 дней',
]

export function EventsPage() {
  const { company } = useCompanyContext()
  const client = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [nlpText, setNlpText] = useState('')
  const [nlpError, setNlpError] = useState('')
  const [nlpFilled, setNlpFilled] = useState<Set<string>>(() => new Set())
  const result = useQuery({ queryKey: keys.events(company?.company_id ?? ''), queryFn: () => api.events(company!.company_id), enabled: Boolean(company) })
  const summary = useSummary(company?.company_id, 90, 0)
  const referenceDate = summary.data?.last_actual_date ?? summary.data?.balance_date ?? localToday()
  const defaultEventDate = addDaysToDate(referenceDate, 3)
  const form = useForm<EventFormInput, unknown, EventValues>({
    resolver: zodResolver(schema),
    defaultValues: { date: defaultEventDate, amount: 10000, direction: 'списание', category: 'Прочие расходы', event_type: 'Пользовательское событие', description: '', counterparty_inn: '', counterparty_name: '', source: 'ручной ввод', status: 'Ожидается' },
  })
  useEffect(() => {
    if (summary.data?.last_actual_date && editingId === null && !form.formState.dirtyFields.date) {
      form.setValue('date', addDaysToDate(summary.data.last_actual_date, 3))
    }
  }, [editingId, form, form.formState.dirtyFields.date, summary.data?.last_actual_date])
  const applyNlp = (text = nlpText) => {
    try {
      const parsed = parseEventText(text, summary.data?.last_actual_date ?? referenceDate)
      const options = { shouldDirty: true, shouldValidate: true }
      form.setValue('date', parsed.date, options)
      form.setValue('amount', parsed.amount, options)
      form.setValue('direction', parsed.direction, options)
      form.setValue('category', parsed.category, options)
      form.setValue('event_type', parsed.event_type, options)
      form.setValue('description', text.trim(), options)
      form.setValue('source', 'Быстрый ввод NLP', options)
      setNlpFilled(new Set(['date', 'amount', 'direction', 'category', 'event_type', 'description', 'source']))
      setNlpError('')
      setMessage('Распознанные значения внесены в форму.')
    } catch (cause) {
      setNlpFilled(new Set())
      setNlpError(cause instanceof Error ? cause.message : 'Не удалось распознать фразу.')
    }
  }
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: keys.events(company?.company_id ?? '') }),
    client.invalidateQueries({ queryKey: ['summary', company?.company_id ?? ''] }),
    client.invalidateQueries({ queryKey: ['forecast', company?.company_id ?? ''] }),
  ])
  const create = useMutation({ mutationFn: (values: EventValues) => api.createEvent(company!.company_id, values), onSuccess: () => { form.reset({ ...form.getValues(), date: defaultEventDate, description: '', counterparty_inn: '', counterparty_name: '' }); setNlpFilled(new Set()); setMessage('Событие сохранено.'); return refresh() } })
  const update = useMutation({ mutationFn: ({ id, event }: { id: number; event: Partial<EventValues> }) => api.updateEvent(company!.company_id, id, event), onSuccess: refresh })
  const cancel = useMutation({ mutationFn: (id: number) => api.cancelEvent(company!.company_id, id), onSuccess: refresh })
  const importFile = useMutation({ mutationFn: (file: File) => api.importEvents(company!.company_id, file), onSuccess: (response) => { setMessage(`Импортировано событий: ${response.imported}`); refresh() } })
  const resetDemo = useMutation({ mutationFn: () => api.resetDemoEvents(company!.company_id), onSuccess: () => { setMessage('Демо-набор из шести событий восстановлен.'); return refresh() } })
  const syncExternalSources = () => {
    setMessage('Демо-синхронизация завершена: счета из 1С и налоги из календаря ФНС успешно подгружены.')
  }
  const onSubmit = form.handleSubmit((values) => {
    if (editingId !== null) {
      update.mutate({ id: editingId, event: values }, { onSuccess: () => { setEditingId(null); form.reset({ ...form.getValues(), date: defaultEventDate, description: '' }); setNlpFilled(new Set()); setMessage('Событие обновлено.') } })
    } else {
      create.mutate(values)
    }
  })
  const categories = ['Выручка и поступления от клиентов','Закупки и поставщики','Фонд оплаты труда','Налоги и обязательные платежи','Аренда','Маркетинг и реклама','Логистика и транспорт','Комиссии банка','Кредиты и проценты','Лизинг','Оборудование и капитальные расходы','Прочие поступления','Прочие расходы']
  const types = ['Счёт клиенту','Ожидаемое поступление','Счёт поставщика','Зарплата','Налоговый платёж (ввод пользователя)','Аренда','Кредит или лизинг','Пользовательское событие']
  return <div className="page-stack"><div className="page-heading"><div><div className="eyebrow">ПЛАНИРУЕМЫЕ ДВИЖЕНИЯ</div><h1>Будущие события</h1><p>События сохраняются локально в SQLite отдельно для каждой компании.</p></div><button className="button secondary" onClick={() => fileInput.current?.click()}><FileUp size={16} />Импорт CSV</button><input ref={fileInput} hidden type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) importFile.mutate(file); event.currentTarget.value = '' }} /></div>
    {message && <div className="notice success-notice">{message}<button aria-label="Закрыть сообщение" onClick={() => setMessage('')}><X size={15} /></button></div>}
    {(create.isError || importFile.isError || update.isError || cancel.isError || resetDemo.isError) && <div className="inline-error">{[create.error, importFile.error, update.error, cancel.error, resetDemo.error].filter(Boolean).map((error) => (error as Error).message).join(' · ')}</div>}
    <div className="content-grid event-grid">
      <section className="card"><div className="card-heading"><div><h2>Добавить событие</h2><p>Налоговые суммы вводятся только пользователем или из файла.</p></div><CalendarPlus className="heading-icon" size={20} /></div>
        <div className="nlp-card"><div><h3>Быстрый ввод фразой (NLP)</h3><p>Относительные даты отсчитываются от последней операции в выписке ({summary.data?.last_actual_date ?? 'загрузка'}).</p></div><textarea aria-label="Фраза для быстрого ввода" rows={2} placeholder="Клиент оплатит 350000 через 15 дней по договору" value={nlpText} onChange={(event) => setNlpText(event.target.value)} /><div className="nlp-actions"><button className="button secondary" type="button" onClick={() => applyNlp()}>Распознать и заполнить</button><div className="nlp-examples">{NLP_EXAMPLES.map((example) => <button key={example} className="button secondary" type="button" onClick={() => { setNlpText(example); applyNlp(example) }}>{example}</button>)}</div></div>{nlpError && <p className="field-error" role="alert">{nlpError}</p>}</div>
        <form className="event-form" onSubmit={onSubmit}>
          <label className={nlpFilled.has('date') ? 'nlp-filled' : ''}>Дата<input type="date" {...form.register('date')} />{form.formState.errors.date && <small className="field-error">{form.formState.errors.date.message}</small>}</label>
          <label className={nlpFilled.has('direction') ? 'nlp-filled' : ''}>Направление<select {...form.register('direction')}><option value="списание">Списание</option><option value="поступление">Поступление</option></select></label>
          <label className={nlpFilled.has('amount') ? 'nlp-filled' : ''}>Сумма, ₽<input type="number" step="0.01" min="0.01" {...form.register('amount')} />{form.formState.errors.amount && <small className="field-error">{form.formState.errors.amount.message}</small>}</label>
          <label className={nlpFilled.has('event_type') ? 'nlp-filled' : ''}>Тип события<select {...form.register('event_type')}>{types.map((type) => <option key={type}>{type}</option>)}</select></label>
          <label className={nlpFilled.has('category') ? 'nlp-filled' : ''}>Категория<select {...form.register('category')}>{categories.map((category) => <option key={category}>{category}</option>)}</select></label>
          <label>Статус<select {...form.register('status')}><option>Ожидается</option><option>Подтверждено</option><option>Исполнено</option><option>Отменено</option></select></label>
          <label className={`full-field ${nlpFilled.has('description') ? 'nlp-filled' : ''}`}>Описание<input placeholder="Например: счёт поставщика за сырьё" {...form.register('description')} /></label>
          <label>Контрагент<input autoComplete="organization" placeholder="Название организации" {...form.register('counterparty_name')} /></label>
          <label>ИНН контрагента<input inputMode="numeric" placeholder="10 или 12 цифр" maxLength={12} {...form.register('counterparty_inn')} /></label>
          <button className="button primary full-field" type="submit" disabled={create.isPending || update.isPending}>{editingId !== null ? 'Сохранить изменения' : 'Сохранить событие'}</button>
          {editingId !== null && <button className="button secondary full-field" type="button" onClick={() => { setEditingId(null); form.reset({ ...form.getValues(), date: defaultEventDate, description: '' }) }}>Отменить редактирование</button>}
        </form>
      </section>
      <section className="card"><div className="card-heading event-list-heading"><div><h2>Список событий</h2><p>Добавление будущего платежа не изменяет историю операций.</p></div><div className="event-header-actions"><button className="button secondary" type="button" onClick={syncExternalSources}><RefreshCw size={16} />Синхронизация с 1С и ФНС</button><button className="button secondary" type="button" disabled={resetDemo.isPending} onClick={() => resetDemo.mutate()}><RotateCcw size={16} />Сбросить к демо-набору</button></div></div>
        <QueryState isLoading={result.isLoading} error={result.error as Error | null}>
          {!result.data?.items.length ? <EmptyState>События ещё не добавлены.</EmptyState> : (
            <div className="event-list">{result.data.items.map((event) => {
              const badge = sourceBadge(event.source)
              return <article className="event-card" key={event.id}>
                <div className="event-card-head">
                  <span className={`direction-tag ${event.direction === 'поступление' ? 'income' : 'expense'}`}>{event.direction}</span>
                  <span className={`source-badge ${badge.tone}`}>{badge.label}</span>
                  <select aria-label={`Статус события ${event.id}`} value={event.status} onChange={(change) => update.mutate({ id: event.id, event: { status: change.target.value as EventValues['status'] } })}>
                    <option>Ожидается</option><option>Подтверждено</option><option>Исполнено</option><option>Отменено</option>
                  </select>
                </div>
                <div className="event-card-title">{event.description || event.event_type}</div>
                <div className="event-card-meta">{dateRu(event.date)} · {event.category}{event.counterparty_name ? ` · ${event.counterparty_name}` : ''}</div>
                {event.counterparty_risk && <span className={`counterparty-risk ${event.counterparty_risk.score >= 80 ? 'high' : event.counterparty_risk.score >= 55 ? 'medium' : 'low'}`} title={`${event.counterparty_risk.advice} ${event.counterparty_risk.source}`}>
                  {event.counterparty_risk.status} · задержка {Math.round(event.counterparty_risk.delay_probability * 100)}%
                </span>}
                <div className="event-card-foot">
                  <strong className={event.direction === 'поступление' ? 'positive' : 'negative'}>{currency(event.direction === 'поступление' ? event.amount : -event.amount)}</strong>
                  <div className="event-actions">{event.status !== 'Отменено' && <>
                    <button aria-label={`Редактировать событие ${event.id}`} className="icon-button edit" onClick={() => {
                      setEditingId(event.id)
                      form.reset({
                        date: event.date, amount: event.amount, direction: event.direction, category: event.category,
                        event_type: event.event_type, description: event.description,
                        counterparty_inn: event.counterparty_inn ?? '',
                        counterparty_name: event.counterparty_name ?? '',
                        source: event.source, status: event.status,
                      })
                    }}><Pencil size={15} /></button>
                    <button aria-label={`Отменить событие ${event.id}`} className="icon-button" onClick={() => cancel.mutate(event.id)}><X size={17} /></button>
                  </>}</div>
                </div>
              </article>
            })}</div>
          )}
        </QueryState>
      </section>
    </div>
  </div>
}
