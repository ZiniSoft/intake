import { describe, expect, it } from 'vitest'

import { clearCursorPagination, readCursorPagination, writeCursorPagination } from './list-url'


describe('shareable cursor pagination URL', () => {
  it('treats the first page as the canonical default', () => {
    expect(readCursorPagination(new URLSearchParams())).toEqual({ page: 1, needsReset: false })
    expect(readCursorPagination(new URLSearchParams('page=1&cursor=stale'))).toEqual({ page: 1, needsReset: true })
  })

  it('requires both a human page and the opaque cursor for a deep link', () => {
    expect(readCursorPagination(new URLSearchParams('page=2&cursor=abc.def'))).toEqual({ page: 2, cursor: 'abc.def', needsReset: false })
    expect(readCursorPagination(new URLSearchParams('page=2'))).toEqual({ page: 1, needsReset: true })
    expect(readCursorPagination(new URLSearchParams('cursor=abc.def'))).toEqual({ page: 1, needsReset: true })
    expect(readCursorPagination(new URLSearchParams('page=02&cursor=abc.def'))).toEqual({ page: 1, needsReset: true })
  })

  it('preserves filters while writing or clearing the page position', () => {
    const filters = new URLSearchParams('project=intake&stage=ACCEPTED&search=preview')
    const pageTwo = writeCursorPagination(filters, 2, 'abc.def')
    expect(pageTwo.toString()).toBe('project=intake&stage=ACCEPTED&search=preview&page=2&cursor=abc.def')
    expect(clearCursorPagination(pageTwo).toString()).toBe('project=intake&stage=ACCEPTED&search=preview')
  })
})
