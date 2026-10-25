import { AlertCircle, FolderOpen, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export function Loading({ label = 'Загружаем данные…' }: { label?: string }) {
  return <div className="state"><LoaderCircle className="spin" size={20} />{label}</div>
}

export function ErrorState({ message }: { message: string }) {
  return <div className="error-state"><AlertCircle size={20} /><span>{message}</span></div>
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>
}

export function CompanyEmptyState({ isAdmin = false }: { isAdmin?: boolean }) {
  return <div className="empty-state">
    <FolderOpen size={28} aria-hidden="true" />
    <h2>Нет данных для отображения</h2>
    <p>Компания не выбрана или по ней отсутствуют операции. Пожалуйста, выберите компанию в верхнем меню или загрузите датасет транзакций.</p>
    {isAdmin && <Link className="button secondary" to="/companies">Загрузить датасет</Link>}
  </div>
}

export function QueryState({ isLoading, error, children }: { isLoading: boolean; error: Error | null; children: ReactNode }) {
  if (isLoading) return <Loading />
  if (error) return <ErrorState message={error.message} />
  return children
}
