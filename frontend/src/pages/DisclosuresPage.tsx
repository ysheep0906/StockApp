import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, ApiError } from '../api'

type Disclosure = {
  rcept_no: string
  stock_code: string
  name: string
  report_nm: string
  rcept_dt: string
  summary: string | null
  summary_status: 'pending' | 'done' | 'failed'
}

type WatchItem = { stock_code: string; name: string }

const DART_VIEWER = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='

function SummaryCell({ d }: { d: Disclosure }) {
  if (d.summary_status === 'done' && d.summary) {
    // LLM 출력은 반드시 '텍스트'로만 표시한다 (HTML로 해석하지 않음)
    return <div style={{ whiteSpace: 'pre-line' }}>{d.summary}</div>
  }
  if (d.summary_status === 'failed') {
    return <span style={{ color: '#999' }}>요약 실패 (원문을 확인하세요)</span>
  }
  return <span style={{ color: '#999' }}>요약 대기 중</span>
}

export default function DisclosuresPage() {
  const [params, setParams] = useSearchParams()
  const stock = params.get('stock') ?? ''
  const [items, setItems] = useState<Disclosure[]>([])
  const [watch, setWatch] = useState<WatchItem[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<WatchItem[]>('/api/watchlist')
      .then(setWatch)
      .catch(() => setWatch([]))
  }, [])

  const load = useCallback(async () => {
    try {
      const query = stock ? `?stock_code=${encodeURIComponent(stock)}` : ''
      setItems(await api<Disclosure[]>(`/api/disclosures${query}`))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '서버에 연결할 수 없습니다')
    }
  }, [stock])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <main style={{ padding: 24 }}>
      <h1>공시</h1>

      <label>
        종목{' '}
        <select
          value={stock}
          onChange={(e) => setParams(e.target.value ? { stock: e.target.value } : {})}
        >
          <option value="">관심종목 전체</option>
          {watch.map((w) => (
            <option key={w.stock_code} value={w.stock_code}>
              {w.name}
            </option>
          ))}
        </select>
      </label>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {!error && items.length === 0 && <p>표시할 공시가 없습니다.</p>}

      {items.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: 'collapse', marginTop: 16 }}>
          <thead>
            <tr>
              <th>날짜</th>
              <th>종목</th>
              <th>공시 제목</th>
              <th style={{ minWidth: 320 }}>AI 3줄 요약</th>
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.rcept_no} style={{ borderTop: '1px solid #eee', verticalAlign: 'top' }}>
                <td>{d.rcept_dt}</td>
                <td>{d.name}</td>
                <td>
                  <a href={DART_VIEWER + d.rcept_no} target="_blank" rel="noopener noreferrer">
                    {d.report_nm}
                  </a>
                </td>
                <td>
                  <SummaryCell d={d} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p style={{ color: '#666', marginTop: 16 }}>
        AI 요약은 원문 앞부분을 바탕으로 자동 생성되며 투자 판단의 근거가 아닙니다. 정확한
        내용은 제목을 눌러 원문을 확인하세요.
      </p>
    </main>
  )
}