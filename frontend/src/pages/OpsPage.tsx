import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api'

type JobState = 'ok' | 'running' | 'stale' | 'failed' | 'stuck' | 'unknown'

type Job = {
  job_name: string
  label: string
  state: JobState
  last_started_at: string | null
  last_status: string | null
  last_rows: number | null
  last_message: string | null
  last_success_at: string | null
  failures_24h: number
}

type Gap = {
  trade_date: string
  stock_code: string
  name: string | null
  gap_start: string
  gap_end: string
  missing_count: number
  recovered_count: number | null
  status: 'detected' | 'recovered' | 'failed'
}

type Failure = { id: number; job_name: string; started_at: string; message: string | null }

type OpsStatus = {
  now: string
  trading: boolean
  overall: 'ok' | 'warn' | 'error'
  jobs: Job[]
  stuck_runs: { id: number; job_name: string; started_at: string }[]
  recent_failures: Failure[]
  gaps: Gap[]
  summary_queue: { pending: number; done: number; failed: number }
}

const STATE_STYLE: Record<JobState, { text: string; color: string }> = {
  ok: { text: '정상', color: '#1a7f37' },
  running: { text: '실행 중', color: '#0969da' },
  stale: { text: '지연', color: '#bf8700' },
  failed: { text: '실패', color: '#cf222e' },
  stuck: { text: '멈춤', color: '#cf222e' },
  unknown: { text: '기록 없음', color: '#6e7781' },
}

const OVERALL_STYLE = {
  ok: { text: '전체 정상', color: '#1a7f37' },
  warn: { text: '주의: 지연된 작업이 있습니다', color: '#bf8700' },
  error: { text: '이상: 실패하거나 멈춘 작업이 있습니다', color: '#cf222e' },
}

const REFRESH_MS = 60_000

// 서버가 준 KST 문자열을 그대로 잘라서 표시 (브라우저 시간대 변환 안 함)
function fmt(ts: string | null): string {
  return ts ? ts.slice(5, 16).replace('T', ' ') : '-'
}

export default function OpsPage() {
  const [data, setData] = useState<OpsStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await api<OpsStatus>('/api/ops/status'))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '서버에 연결할 수 없습니다')
    }
  }, [])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  if (!data) {
    return <main style={{ padding: 24 }}>{error ?? '불러오는 중...'}</main>
  }

  const overall = OVERALL_STYLE[data.overall]

  return (
    <main style={{ padding: 24 }}>
      <h1>운영 현황</h1>
      <p style={{ color: '#666' }}>
        조회 시각 {fmt(data.now)} · {data.trading ? '장 운영 중' : '장 마감'} · 1분마다 자동 갱신
      </p>
      {error && <p style={{ color: 'crimson' }}>갱신 실패: {error} (마지막 데이터 표시 중)</p>}

      <p style={{ fontWeight: 'bold', color: overall.color }}>{overall.text}</p>

      <h2>작업 상태</h2>
      <table cellPadding={6} style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th>작업</th>
            <th>상태</th>
            <th>마지막 실행</th>
            <th>마지막 성공</th>
            <th>24시간 실패</th>
            <th>마지막 메시지</th>
          </tr>
        </thead>
        <tbody>
          {data.jobs.map((j) => (
            <tr key={j.job_name} style={{ borderTop: '1px solid #eee' }}>
              <td>{j.label}</td>
              <td style={{ color: STATE_STYLE[j.state].color, fontWeight: 'bold' }}>
                {STATE_STYLE[j.state].text}
              </td>
              <td>{fmt(j.last_started_at)}</td>
              <td>{fmt(j.last_success_at)}</td>
              <td style={{ textAlign: 'center' }}>{j.failures_24h}</td>
              <td style={{ color: '#666', maxWidth: 360 }}>{j.last_message ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {data.stuck_runs.length > 0 && (
        <>
          <h2 style={{ color: '#cf222e' }}>멈춘 작업 (비정상 종료 의심)</h2>
          <ul>
            {data.stuck_runs.map((s) => (
              <li key={s.id}>
                #{s.id} {s.job_name} · 시작 {fmt(s.started_at)}
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>공시 요약 대기열</h2>
      <p>
        대기 {data.summary_queue.pending} · 완료 {data.summary_queue.done} · 실패{' '}
        {data.summary_queue.failed}
      </p>

      <h2>최근 7일 수집 누락</h2>
      {data.gaps.length === 0 ? (
        <p>감지된 누락이 없습니다.</p>
      ) : (
        <table cellPadding={6} style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>날짜</th>
              <th>종목</th>
              <th>구간</th>
              <th>누락</th>
              <th>복구</th>
              <th>결과</th>
            </tr>
          </thead>
          <tbody>
            {data.gaps.map((g, i) => (
              <tr key={i} style={{ borderTop: '1px solid #eee' }}>
                <td>{g.trade_date}</td>
                <td>{g.name ?? g.stock_code}</td>
                <td>
                  {g.gap_start.slice(11, 16)}~{g.gap_end.slice(11, 16)}
                </td>
                <td>{g.missing_count}분</td>
                <td>{g.recovered_count ?? 0}분</td>
                <td style={{ color: g.status === 'recovered' ? '#1a7f37' : '#cf222e' }}>
                  {g.status === 'recovered' ? '복구됨' : '복구 실패'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>최근 실패 기록</h2>
      {data.recent_failures.length === 0 ? (
        <p>실패 기록이 없습니다.</p>
      ) : (
        <ul>
          {data.recent_failures.map((f) => (
            <li key={f.id}>
              {fmt(f.started_at)} · {f.job_name} · {f.message ?? '(메시지 없음)'}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}