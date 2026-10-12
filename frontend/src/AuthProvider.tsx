import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError } from './api'
import { AuthContext } from './auth'
import type { User } from './auth'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // 앱이 처음 열릴 때 세션이 유효한지 서버에 확인
  useEffect(() => {
    api<User>('/api/auth/me')
      .then(setUser)
      .catch((e: unknown) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const u = await api<User>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setUser(u)
  }, [])

  const logout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}