import { useState } from 'react'
import { parseInput, toInput } from '../lib/numberInput.ts'

interface Props {
  value: number
  onChange: (value: number) => void
  label: string
  invalidMessage: string
}

/** A text field for a number that keeps what is being typed until it is left, and reports only valid numbers. */
export function NumberField({ value, onChange, label, invalidMessage }: Props) {
  const [draft, setDraft] = useState<string | null>(null)
  const invalid = draft !== null && parseInput(draft) === null
  return (
    <input
      type="text"
      inputMode="decimal"
      className="number-field"
      aria-label={label}
      aria-invalid={invalid || undefined}
      title={invalid ? invalidMessage : undefined}
      value={draft ?? toInput(value)}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => {
        setDraft(e.target.value)
        const parsed = parseInput(e.target.value)
        if (parsed !== null) onChange(parsed)
      }}
      onBlur={() => setDraft(null)}
    />
  )
}
