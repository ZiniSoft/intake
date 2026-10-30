import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react'

export type Locale = 'vi' | 'en'

const STORAGE_KEY = 'intake.locale'

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  text: (vi: string, en: string) => string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

export function resolveLocale(search: string, stored: string | null): Locale {
  const requested = new URLSearchParams(search).get('lang')
  if (requested === 'en' || requested === 'vi') return requested
  return stored === 'en' || stored === 'vi' ? stored : 'vi'
}

export function localeText(locale: Locale, vi: string, en: string): string {
  return locale === 'en' ? en : vi
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    try {
      return resolveLocale(window.location.search, window.localStorage.getItem(STORAGE_KEY))
    } catch {
      return 'vi'
    }
  })

  useEffect(() => {
    document.documentElement.lang = locale
    try { window.localStorage.setItem(STORAGE_KEY, locale) } catch { /* private browsing may block storage */ }
  }, [locale])

  const value = useMemo<LocaleContextValue>(() => ({
    locale,
    setLocale,
    text: (vi, en) => localeText(locale, vi, en),
  }), [locale])

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext)
  if (!value) throw new Error('useLocale must be used inside LocaleProvider')
  return value
}
