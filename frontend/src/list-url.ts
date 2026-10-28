export type CursorPagination = {
  page: number
  cursor?: string
  needsReset: boolean
}

/**
 * Read the shareable keyset position used by list pages.
 * Page is human-facing only; cursor remains the API source of truth.
 */
export function readCursorPagination(params: URLSearchParams): CursorPagination {
  const rawPage = params.get('page')
  const cursor = params.get('cursor')?.trim() || undefined

  if (rawPage === null && cursor === undefined) return { page: 1, needsReset: false }
  if (rawPage === null || !/^[1-9]\d*$/.test(rawPage)) return { page: 1, needsReset: true }

  const page = Number(rawPage)
  if (!Number.isSafeInteger(page) || page < 2 || cursor === undefined) {
    return { page: 1, needsReset: true }
  }
  return { page, cursor, needsReset: false }
}

export function clearCursorPagination(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params)
  next.delete('page')
  next.delete('cursor')
  return next
}

export function writeCursorPagination(params: URLSearchParams, page: number, cursor?: string): URLSearchParams {
  const next = clearCursorPagination(params)
  if (page > 1 && cursor) {
    next.set('page', String(page))
    next.set('cursor', cursor)
  }
  return next
}
