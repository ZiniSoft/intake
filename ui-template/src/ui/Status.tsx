import { ReactNode } from 'react'

export type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info' | 'accent'

// A short label for the state of something: two or three words, never a sentence.
export function Status({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`ui-status ui-tone-${tone}`}>{children}</span>
}
