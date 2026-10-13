import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, ApiError } from '../api'

type DashItem = {
  stock_code: string
  name: string
  price: number | null
  change_rate: number | null
  ts: string | null
  stale: boolean
}

type Dashboard = { now: string; trading: boolean; items: DashItem[] }

const REFRESH_MS = 60_000

// 한국 증권 화면 관례: 상승은 빨강, 하락은 파랑
function rateColor(rate: number | null): string {
  if (rate === null || rate === 0) return 'inherit'
  return rate > 0 ? '#d60000' : '#0050d6'
}

function formatRate(rate: number | null): string {
  if (rate === null) return '-'
  return `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%`
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await api<Dashboard>('/api/dashboard'))
      setError(null)
    } catch (e) {
      // 실패해도 이전 데이터는 그대로 두고 오류만 표시
      setError(e instanceof ApiError ? e.message : '서버에 연결할 수 없습니다')
    }
  }, [])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(id)   // 페이지를 떠나면 자동 갱신 중지
  }, [load])

  return (
    <main style={{ padding: 24 }}>
      <h1>대시보드</h1>
      {data && (
        <p style={{ color: '#666' }}>
          {data.trading ? '장 운영 중' : '장 마감'} · 조회 시각 {data.now.slice(11, 16)} · 1분마다
          자동 갱신
        </p>
      )}
      {error && <p style={{ color: 'crimson' }}>{error}</p>}

      {data && data.items.length === 0 && (
        <p>
          등록된 관심종목이 없습니다. <Link to="/watchlist">관심종목 추가하기</Link>
        </p>
      )}

      {data && data.items.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>종목</th>
              <th style={{ textAlign: 'right' }}>현재가</th>
              <th style={{ textAlign: 'right' }}>등락률</th>
              <th>기준 시각</th>
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.stock_code}>
                <td>
                  <Link to={`/stocks/${item.stock_code}`}>
                    {item.name} ({item.stock_code})
                  </Link>
                </td>
                <td style={{ textAlign: 'right' }}>
                  {item.price === null ? '-' : item.price.toLocaleString('ko-KR')}
                </td>
                <td style={{ textAlign: 'right', color: rateColor(item.change_rate) }}>
                  {formatRate(item.change_rate)}
                </td>
                <td>{item.ts ? item.ts.slice(5, 16).replace('T', ' ') : '-'}</td>
                <td>{item.stale ? '⚠ 지연' : '정상'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  )
}