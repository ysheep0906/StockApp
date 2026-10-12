import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../auth'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  // 서버 확인이 끝나기 전에는 판단하지 않음 (새로고침 시 로그인 화면이 깜빡이는 문제 방지)
  if (loading) return <p style={{ padding: 24 }}>확인 중...</p>

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}