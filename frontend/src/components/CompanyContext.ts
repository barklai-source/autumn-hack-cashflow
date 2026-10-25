import { useOutletContext } from 'react-router-dom'
import type { AuthSession, Company } from '../types/api'

export function useCompanyContext() {
  return useOutletContext<{ company?: Company; dataAvailable: boolean; user?: AuthSession }>()
}
