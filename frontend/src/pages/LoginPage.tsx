import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, CircleDollarSign, LogIn, Search } from 'lucide-react'
import { api } from '../api/client'
import type { AuthSession, InnLookup } from '../types/api'
import './login.css'

type LoginTab = 'login' | 'register'
type Credentials = { username: string; password: string }

export function LoginPage({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const [tab, setTab] = useState<LoginTab>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [inn, setInn] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [lookupResult, setLookupResult] = useState<InnLookup | null>(null)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const demoCompanies = useQuery({ queryKey: ['auth-demo-companies'], queryFn: api.demoCompanies })

  const submit = async ({ username: login, password: pass }: Credentials) => {
    setError('')
    setIsLoading(true)
    try {
      onLogin(await api.login(login, pass))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось выполнить вход.')
    } finally {
      setIsLoading(false)
    }
  }

  const lookup = async (value: string) => {
    setError('')
    setLookupResult(null)
    setIsLoading(true)
    try {
      const result = await api.lookupInn(value)
      setLookupResult(result)
      if (result.found && result.name) setCompanyName((current) => current || result.name!)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось найти организацию.')
    } finally {
      setIsLoading(false)
    }
  }

  const register = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      onLogin(await api.register(inn, password, companyName.trim() || undefined))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось зарегистрировать пользователя.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogin = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void submit({ username, password })
  }

  const startDemoRegistration = (demoInn: string) => {
    setTab('register')
    setInn(demoInn)
    setPassword('')
    setCompanyName('')
    void lookup(demoInn)
  }

  return <main className="login-screen">
    <section className="login-panel">
      <div className="login-brand"><span className="brand-icon"><CircleDollarSign size={23} /></span><span>Кэшфлоу<small>ФИНАНСЫ БИЗНЕСА</small></span></div>
      <div className="login-heading"><div className="eyebrow">ЗАЩИЩЁННЫЙ ДОСТУП</div><h1>{tab === 'login' ? 'Вход в систему' : 'Регистрация компании'}</h1><p>Подключите компанию по ИНН, чтобы открыть финансовое пространство.</p></div>
      <div className="auth-tabs" role="tablist" aria-label="Авторизация">
        <button type="button" role="tab" aria-selected={tab === 'login'} className={tab === 'login' ? 'active' : ''} onClick={() => { setTab('login'); setError('') }}>Вход по ИНН</button>
        <button type="button" role="tab" aria-selected={tab === 'register'} className={tab === 'register' ? 'active' : ''} onClick={() => { setTab('register'); setError('') }}>Регистрация по ИНН</button>
      </div>
      {tab === 'login' ? <form className="login-form" onSubmit={handleLogin}>
        <label>ИНН или логин<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="10 или 12 цифр либо admin" required /></label>
        <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button className="button primary login-submit" type="submit" disabled={isLoading}>{isLoading ? 'Входим…' : 'Войти'} <LogIn size={17} /></button>
      </form> : <form className="login-form" onSubmit={(event) => { void register(event) }}>
        <label>ИНН организации<input inputMode="numeric" autoComplete="off" value={inn} onChange={(event) => { setInn(event.target.value.replace(/\D/g, '').slice(0, 12)); setLookupResult(null) }} minLength={10} maxLength={12} pattern="\d{10}|\d{12}" placeholder="10 или 12 цифр" required /></label>
        <button className="button secondary lookup-button" type="button" disabled={isLoading || !/^\d{10}(\d{2})?$/.test(inn)} onClick={() => void lookup(inn)}><Search size={16} /> Найти организацию по ИНН</button>
        {lookupResult?.found && <div className="inn-result found"><Building2 size={18} /><span><strong>Найдена компания: {lookupResult.name}, {lookupResult.company_id}</strong><small>{lookupResult.industry || 'Отрасль не указана'}</small></span></div>}
        {lookupResult && !lookupResult.found && <div className="inn-result"><Building2 size={18} /><span><strong>Организация не найдена в демо-справочнике</strong><small>Для демонстрации будет подключён профиль компании по указанному названию.</small></span></div>}
        <label>Название организации (необязательно)<input autoComplete="organization" value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Например, ООО Грузоперевозки" /></label>
        <label>Пароль<input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button className="button primary login-submit" type="submit" disabled={isLoading || !/^\d{10}(\d{2})?$/.test(inn)}>{isLoading ? 'Подключаем…' : 'Зарегистрировать и подключить счета'} <LogIn size={17} /></button>
      </form>}
      <div className="demo-logins"><h2>Быстрый вход</h2>
        <button className="button primary" type="button" disabled={isLoading || !(demoCompanies.data?.items.length)} onClick={() => {
          const company = demoCompanies.data?.items[0]
          if (company) void submit({ username: company.inn, password: '1234' })
        }}>Войти как Предприниматель</button>
        <button className="button secondary" type="button" disabled={isLoading} onClick={() => void submit({ username: 'admin', password: 'admin' })}>Войти как Стенд жюри / Админ</button>
        <h2>Другие демо-компании</h2>
        {(demoCompanies.data?.items ?? []).map((company) => <button key={company.company_id} className="button secondary" type="button" disabled={isLoading} onClick={() => void submit({ username: company.inn, password: '1234' })}>Войти по ИНН {company.inn} ({company.company_id})</button>)}
        {(demoCompanies.data?.items.length ?? 0) > 1 && <button className="button secondary" type="button" disabled={isLoading} onClick={() => startDemoRegistration(demoCompanies.data!.items[1].inn)}>Протестировать регистрацию по ИНН {demoCompanies.data!.items[1].inn}</button>}
        <button className="button secondary" type="button" disabled={isLoading} onClick={() => void submit({ username: 'admin', password: 'admin' })}>Администратор банка (admin)</button>
      </div>
    </section>
  </main>
}
