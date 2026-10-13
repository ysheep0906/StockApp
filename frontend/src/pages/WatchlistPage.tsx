import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api'

type Stock = { code: string; name: string }

type WatchItem = {
  stock_code: string
  name: string
  alert_up_pct: number | null
  alert_down_pct: number | null
}

const WATCHLIST_MAX = 10

function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : '서버에 연결할 수 없습니다'
}

function WatchRow({
  item,
  onSave,
  onRemove,
}: {
  item: WatchItem
  onSave: (code: string, up: string, down: string) => Promise<void>
  onRemove: (code: string) => Promise<void>
}) {
  const [up, setUp] = useState(item.alert_up_pct?.toString() ?? '')
  const [down, setDown] = useState(item.alert_down_pct?.toString() ?? '')

  return (
    <tr>
      <td>{item.stock_code}</td>
      <td>{item.name}</td>
      <td>
        +<input type="number" step="0.01" min="0.01" max="30" value={up}
          onChange={(e) => setUp(e.target.value)} style={{ width: 70 }} />%
      </td>
      <td>
        -<input type="number" step="0.01" min="0.01" max="30" value={down}
          onChange={(e) => setDown(e.target.value)} style={{ width: 70 }} />%
      </td>
      <td>
        <button onClick={() => void onSave(item.stock_code, up, down)}>알림 저장</button>{' '}
        <button onClick={() => void onRemove(item.stock_code)}>삭제</button>
      </td>
    </tr>
  )
}

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchItem[]>([])
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Stock[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setItems(await api<WatchItem[]>('/api/watchlist'))
    } catch (e) {
      setError(errMsg(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  function reset() {
    setError(null)
    setMessage(null)
  }

  async function search() {
    reset()
    try {
      setResults(await api<Stock[]>(`/api/stocks/search?q=${encodeURIComponent(query)}`))
    } catch (e) {
      setError(errMsg(e))
    }
  }

  async function add(code: string) {
    reset()
    try {
      await api('/api/watchlist', {
        method: 'POST',
        body: JSON.stringify({ stock_code: code }),
      })
      await load()
    } catch (e) {
      setError(errMsg(e))
    }
  }

  async function saveAlerts(code: string, up: string, down: string) {
    reset()
    try {
      await api(`/api/watchlist/${code}/alerts`, {
        method: 'PUT',
        body: JSON.stringify({
          alert_up_pct: up === '' ? null : Number(up),
          alert_down_pct: down === '' ? null : Number(down),
        }),
      })
      setMessage(`${code} 알림 설정을 저장했습니다`)
      await load()
    } catch (e) {
      setError(errMsg(e))
    }
  }

  async function remove(code: string) {
    if (!confirm(`${code} 종목을 관심종목에서 삭제할까요?`)) return
    reset()
    try {
      await api(`/api/watchlist/${code}`, { method: 'DELETE' })
      await load()
    } catch (e) {
      setError(errMsg(e))
    }
  }

  const registered = new Set(items.map((i) => i.stock_code))

  return (
    <main style={{ padding: 24 }}>
      <h1>관심종목 ({items.length}/{WATCHLIST_MAX})</h1>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {message && <p style={{ color: 'green' }}>{message}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void search()
        }}
        style={{ marginBottom: 16 }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="종목명 또는 종목코드"
          required
        />{' '}
        <button type="submit">검색</button>
      </form>

      {results.length > 0 && (
        <ul>
          {results.map((s) => (
            <li key={s.code}>
              {s.code} {s.name}{' '}
              <button onClick={() => void add(s.code)} disabled={registered.has(s.code)}>
                {registered.has(s.code) ? '등록됨' : '추가'}
              </button>
            </li>
          ))}
        </ul>
      )}

      <table cellPadding={6} style={{ borderCollapse: 'collapse', marginTop: 16 }}>
        <thead>
          <tr>
            <th>코드</th>
            <th>종목명</th>
            <th>상승 알림</th>
            <th>하락 알림</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <WatchRow key={item.stock_code} item={item} onSave={saveAlerts} onRemove={remove} />
          ))}
        </tbody>
      </table>
      <p style={{ color: '#666' }}>알림 칸을 비워두면 해당 알림은 꺼집니다.</p>
    </main>
  )
}