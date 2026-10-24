import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Activity, BarChart3, Building2, CalendarClock, ChevronDown, CircleDollarSign, LayoutDashboard, LogOut, Repeat2, Sparkles, WalletCards } from 'lucide-react'
import { useCompanies, useHealth } from '../hooks/queries'
import type { AuthSession, Company } from '../types/api'

const navigation = [
  { to: '/', label: 'Обзор', icon: LayoutDashboard },
  { to: '/forecast', label: 'Прогноз и риски', icon: Activity },
  { to: '/operations', label: 'Операции', icon: WalletCards },
  { to: '/categories', label: 'Категории', icon: BarChart3 },
  { to: '/recurring', label: 'Регулярные платежи', icon: Repeat2 },
  { to: '/events', label: 'Будущие события', icon: CalendarClock },
  { to: '/quality', label: 'Качество модели', icon: Sparkles },
  { to: '/companies', label: 'Все компании', icon: Building2 },
]

export function Shell({ user, onLogout }: { user: AuthSession; onLogout: () => void }) {
  const location = useLocation()
  const health = useHealth()
  const companies = useCompanies()
  const [companyId, setCompanyId] = useState(() => localStorage.getItem('selected-company') ?? '')
  const items = companies.data?.items ?? []
  const isCompanyUser = user.role === 'company'
  const selectedCompanyId = isCompanyUser ? user.company_id : companyId
  const activeCompany = items.find((company) => company.company_id === selectedCompanyId) ?? items[0]
  const visibleNavigation = navigation.filter((item) => user.role === 'admin' || item.to !== '/companies')
  const serviceStatus = health.isLoading
    ? { label: 'Проверка backend…', title: undefined, online: false }
    : health.isError
      ? { label: 'Backend недоступен', title: health.error.message, online: false }
      : health.data?.data_available
        ? { label: 'Данные подключены', title: health.data.message, online: true }
        : { label: 'Датасет не подключён', title: health.data?.message, online: false }

  useEffect(() => {
    if (!isCompanyUser && activeCompany && activeCompany.company_id !== companyId) setCompanyId(activeCompany.company_id)
  }, [activeCompany, companyId, isCompanyUser])

  const selectCompany = (company: Company) => {
    localStorage.setItem('selected-company', company.company_id)
    setCompanyId(company.company_id)
  }

  useEffect(() => {
    const handleCompanyChange = (event: Event) => {
      const selectedId = (event as CustomEvent<string>).detail
      if (selectedId && !isCompanyUser) setCompanyId(selectedId)
    }
    window.addEventListener('cashflow-company-selected', handleCompanyChange)
    return () => window.removeEventListener('cashflow-company-selected', handleCompanyChange)
  }, [isCompanyUser])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/"><span className="brand-icon"><CircleDollarSign size={22} /></span><span>Кэшфлоу<small>ФИНАНСЫ БИЗНЕСА</small></span></Link>
        <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <nav>{visibleNavigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={18} /><span>{label}</span></NavLink>)}
          <button className="nav-link logout-button" onClick={onLogout} aria-label="Выйти"><LogOut size={18} /><span>Выйти</span></button>
        </nav>
        <div className="sidebar-bottom">
          <div className={`service-status ${serviceStatus.online ? 'online' : 'offline'}`} title={serviceStatus.title}><span />{serviceStatus.label}</div>
          <div className="privacy-note">Локальная обработка<br />без внешней передачи выписок</div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">Пространство / <strong>{navigation.find((item) => item.to === location.pathname)?.label ?? 'Аналитика'}</strong></div>
          <div className="company-picker">
            <Building2 size={16} />
            {isCompanyUser ? <><span>{user.display_name || activeCompany?.name}</span>{(user.inn || activeCompany?.inn) && <span className="inn-badge">ИНН {user.inn || activeCompany?.inn}</span>}<span className="role-badge">Кабинет компании</span></> : companies.isLoading ? <span>Загрузка компаний…</span> : (
              <select aria-label="Выберите компанию" value={activeCompany?.company_id ?? ''} onChange={(event) => {
                const selected = items.find((item) => item.company_id === event.target.value)
                if (selected) selectCompany(selected)
              }}>
                {!items.length && <option value="">Нет компаний</option>}
                {items.map((company) => <option key={company.company_id} value={company.company_id}>{company.company_id} · {company.name}</option>)}
              </select>
            )}
            {isCompanyUser ? null : <><ChevronDown size={14} /><span className="role-badge admin-badge">Администратор</span></>}
          </div>
        </header>
        <section className="content"><Outlet context={{ company: activeCompany, dataAvailable: health.data?.data_available ?? false, user }} /></section>
      </main>
    </div>
  )
}
