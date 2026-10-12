export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// 모든 API 호출은 이 함수를 거친다. 경로는 항상 '/api/...' 상대 경로로 쓴다.
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
  })

  const text = await res.text()
  const data = text ? JSON.parse(text) : null

  if (!res.ok) {
    // FastAPI는 오류 메시지를 detail에 담아 보냄 (입력값 오류 422는 배열이라 문자열일 때만 사용)
    const message =
      data && typeof data.detail === 'string' ? data.detail : `요청 실패 (${res.status})`
    throw new ApiError(res.status, message)
  }
  return data as T
}