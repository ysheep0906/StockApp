import { useEffect, useState } from 'react'

// 백엔드 /api/health 응답 구조 (backend/app/main.py 와 맞춰야 함)
type HealthResponse = {
  status: 'ok' | 'error'
  db: 'ok' | 'unreachable'
  time: string
}

type HealthState = HealthResponse & { httpStatus: number }

function App() {
  const [health, setHealth] = useState<HealthState | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then(async (res) => {
        const data = (await res.json()) as HealthResponse
        setHealth({ httpStatus: res.status, ...data })
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e))
      })
  }, [])

  return (
    <main style={{ padding: 24, fontFamily: 'sans-serif' }}>
      <h1>Stock Monitor</h1>
      {error && <p>API 연결 실패: {error}</p>}
      {health ? (
        <pre>{JSON.stringify(health, null, 2)}</pre>
      ) : (
        !error && <p>확인 중...</p>
      )}
    </main>
  )
}

export default App