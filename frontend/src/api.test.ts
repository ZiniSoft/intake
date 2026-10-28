import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, formatError } from './api'


afterEach(() => {
  vi.unstubAllGlobals()
})


describe('API contract', () => {
  it('unwraps the success envelope', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ success: true, data: { id: 'intake-1' }, request_id: 'req-success' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))

    await expect(api<{ id: string }>('/intakes/intake-1')).resolves.toEqual({ id: 'intake-1' })
  })

  it('keeps stable error code and request id for stale UI recovery', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({
        success: false,
        error: 'STALE_VERSION',
        message: 'Intake changed',
        request_id: 'req-stale',
      }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    )))

    try {
      await api('/intakes/intake-1/review', { method: 'PATCH', body: '{}' })
      throw new Error('Expected request to fail')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({ status: 409, code: 'STALE_VERSION', requestId: 'req-stale' })
      expect(formatError(error)).toContain('Hãy tải phiên bản mới')
    }
  })

  it('shows the server message for a retryable service error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ success: false, error: 'SERVICE_UNAVAILABLE', message: 'Dịch vụ tạm thời chưa sẵn sàng.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )))

    await expect(api('/operations/status')).rejects.toMatchObject({
      status: 503,
      code: 'SERVICE_UNAVAILABLE',
      message: 'Dịch vụ tạm thời chưa sẵn sàng.',
    })
  })

  it('does not collapse a login 401 into a successful response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ success: false, error: 'UNAUTHORIZED', message: 'Invalid credentials' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )))

    await expect(api('/auth/login', { method: 'POST', body: '{}' })).rejects.toMatchObject({
      status: 401,
      code: 'UNAUTHORIZED',
    })
  })
})
