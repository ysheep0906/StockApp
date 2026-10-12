import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api'
import { useAuth } from '../auth'

type Health = { status: string; db: string; time: string }

export default function DashboardPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    api<Health>('/api/health')
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <main style={{ padding: 24, fontFamily: 'sans-serif' }}>
      <h1>대시보드</h1>
      <p>{user?.username} 님 로그인 중</p>
      <p>API 상태: {health ? `${health.status} / DB ${health.db}` : '확인 불가'}</p>
      <button onClick={() => void handleLogout()}>로그아웃</button>
    </main>
  )
}