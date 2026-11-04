const API_ROOT = '/api/v1'
export const AUTH_EXPIRED_EVENT = 'intake:auth-expired'

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const prefix = `${encodeURIComponent(name)}=`
  return document.cookie
    .split('; ')
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length)
}

export class ApiError extends Error {
  status: number
  code?: string
  requestId?: string

  constructor(message: string, status: number, code?: string, requestId?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCookie('intake_csrf')
    if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  })

  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && typeof window !== 'undefined') {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    const message = body.message || body.detail || body.error?.message || 'Không thể hoàn tất yêu cầu.'
    const code = typeof body.error === 'string' ? body.error : undefined
    throw new ApiError(
      message,
      response.status,
      code,
      body.request_id || response.headers.get('X-Request-ID') || undefined,
    )
  }
  if (body.success === true && Object.prototype.hasOwnProperty.call(body, 'data')) {
    return body.data as T
  }
  return body as T
}

export function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc thông tin đăng nhập không đúng.'
    if (error.code === 'STALE_VERSION' || error.status === 409) return 'Dữ liệu đã thay đổi. Hãy tải phiên bản mới trước khi tiếp tục.'
    if (error.code === 'PLANNING_ASSIGNMENT_NOT_FOUND') return 'Kế hoạch đã đổi nên việc này không còn ở vị trí cũ. Hãy tải lại trang rồi báo lại.'
    return error.message
  }
  return error instanceof Error ? error.message : 'Đã xảy ra lỗi không xác định.'
}
