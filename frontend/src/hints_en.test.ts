import { describe, expect, it } from 'vitest'
import { ALL_HINTS, ALL_INTROS } from './hints'
import { HINTS_EN, INTROS_EN } from './hints_en'

// The public guide shows every hint in English (FR-UI-18); a new Vietnamese hint without an English one fails here.
describe('English hints', () => {
  it('covers every hint key and nothing more', () => {
    expect(Object.keys(HINTS_EN).sort()).toEqual(Object.keys(ALL_HINTS).sort())
    for (const value of Object.values(HINTS_EN)) {
      expect(value.label && value.what && value.do).toBeTruthy()
    }
  })

  it('covers every page introduction with the same number of lines', () => {
    expect(Object.keys(INTROS_EN).sort()).toEqual(Object.keys(ALL_INTROS).sort())
    for (const [page, intro] of Object.entries(ALL_INTROS)) {
      expect(INTROS_EN[page].lines.length).toBe(intro.lines.length)
    }
  })
})
