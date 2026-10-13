import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, ApiError } from '../api'

type Point = { ts: string; price: number; source: 'poll' | 'backfill' }
type ChartData = { code: string; name: string; date: string | null; points: Point[] }
type SeriesPoint = { time: string; price: number | null }

const HOUR_TICKS = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '15:30']

// 09:00~15:30 의 모든 분을 만들고, 데이터가 없는 분은 null 로 채운다
// → 차트에서 누락 구간이 끊어진 선으로 보인다
function buildSeries(points: Point[]): SeriesPoint[] {
  const byMinute = new Map(points.map((p) => [p.ts.slice(11, 16), p.price]))
  const series: SeriesPoint[] = []
  for (let m = 9 * 60; m <= 15 * 60 + 30; m++) {
    const time = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
    series.push({ time, price: byMinute.get(time) ?? null })
  }
  return series
}

// 첫 데이터와 마지막 데이터 사이에서 비어 있는 분의 수
function countGaps(series: SeriesPoint[]): number {
  const first = series.findIndex((p) => p.price !== null)
  const last = series.map((p) => p.price !== null).lastIndexOf(true)
  if (first === -1) return 0
  return series.slice(first, last + 1).filter((p) => p.price === null).length
}

export default function StockDetailPage() {
  const { code } = useParams()
  const [day, setDay] = useState('')   // 비어 있으면 가장 최근 날짜
  const [data, setData] = useState<ChartData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!code) return
    try {
      const query = day ? `?date=${day}` : ''
      setData(await api<ChartData>(`/api/stocks/${code}/chart${query}`))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '서버에 연결할 수 없습니다')
    }
  }, [code, day])

  useEffect(() => {
    void load()
  }, [load])

  const series = useMemo(() => buildSeries(data?.points ?? []), [data])
  const gaps = useMemo(() => countGaps(series), [series])
  const backfilled = data?.points.filter((p) => p.source === 'backfill').length ?? 0

  return (
    <main style={{ padding: 24 }}>
      <p>
        <Link to="/">← 대시보드</Link>
      </p>
      <h1>
        {data?.name ?? code} ({code})
      </h1>

      <label>
        날짜 <input type="date" value={day || data?.date || ''} onChange={(e) => setDay(e.target.value)} />
      </label>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}

      {data && data.points.length === 0 && <p>해당 날짜에 수집된 데이터가 없습니다.</p>}

      {data && data.points.length > 0 && (
        <>
          <p style={{ color: '#666' }}>
            수집 {data.points.length}분 · 누락 {gaps}분 · 재수집 {backfilled}건
          </p>
          <div style={{ width: '100%', maxWidth: 900, height: 360 }}>
            <ResponsiveContainer>
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" ticks={HOUR_TICKS} />
                <YAxis domain={['auto', 'auto']} width={80} />
                <Tooltip />
                <Line
                  type="linear"
                  dataKey="price"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </main>
  )
}