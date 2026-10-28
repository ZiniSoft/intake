import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { en } from './en'
import { vi } from './vi'

// Every word shown on screen comes from the two dictionaries. Vietnamese is the source; English must have the same keys.
export type MessageKey = keyof typeof vi
export type Language = 'vi' | 'en'
export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string

const dictionaries: Record<Language, Record<MessageKey, string>> = { vi, en }
const STORAGE_KEY = 'ui.language'

const I18nContext = createContext<{ language: Language; setLanguage: (language: Language) => void; t: Translate } | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'vi'))
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, language)
    document.documentElement.lang = language
  }, [language])
  // "{name}" in a message is replaced by values.name. A message written as "one form | other form" picks the first
  // when values.count is 1 and the second otherwise; a language with a single form writes the message once.
  const t = useCallback<Translate>((key, values) => {
    const forms = dictionaries[language][key].split(' | ')
    const text = forms.length === 2 && values && Number(values.count) !== 1 ? forms[1] : forms[0]
    return values ? text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole)) : text
  }, [language])
  const value = useMemo(() => ({ language, setLanguage, t }), [language, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside I18nProvider')
  return context
}

// Dates and numbers follow the chosen language too.
export function useFormat() {
  const { language } = useI18n()
  const locale = language === 'vi' ? 'vi-VN' : 'en-GB'
  return useMemo(() => ({
    // A calendar day ("2026-10-12") has no time zone: it is read as that day here, not as midnight in London.
    date: (value: string | Date) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value)),
    dateTime: (value: string | Date) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)),
    number: (value: number) => new Intl.NumberFormat(locale).format(value),
  }), [locale])
}
