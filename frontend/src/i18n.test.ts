import { describe, expect, it } from 'vitest'

import { localeText, resolveLocale } from './i18n'

describe('locale selection', () => {
  it('uses an explicit query parameter before stored preference', () => {
    expect(resolveLocale('?lang=en', 'vi')).toBe('en')
    expect(resolveLocale('?lang=vi', 'en')).toBe('vi')
  })

  it('falls back to the stored preference and then English', () => {
    expect(resolveLocale('', 'en')).toBe('en')
    expect(resolveLocale('', 'vi')).toBe('vi')
    expect(resolveLocale('', null)).toBe('en')
  })

  it('returns the text for the selected locale', () => {
    expect(localeText('vi', 'Tạo Intake', 'Create Intake')).toBe('Tạo Intake')
    expect(localeText('en', 'Tạo Intake', 'Create Intake')).toBe('Create Intake')
  })
})
