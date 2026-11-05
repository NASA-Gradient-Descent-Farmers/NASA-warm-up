import { describe, expect, it } from 'vitest'
import { parseInput, toInput } from './numberInput.ts'

describe('parseInput', () => {
  it('reads plain numbers, decimals and thousands separators', () => {
    expect(parseInput('7981.46')).toBe(7981.46)
    expect(parseInput('7,500')).toBe(7500)
    expect(parseInput('7 500')).toBe(7500)
    expect(parseInput('0')).toBe(0)
    expect(parseInput('.5')).toBe(0.5)
    expect(parseInput('12.')).toBe(12)
  })

  it('refuses empty text, signs, letters and a lone dot', () => {
    for (const text of ['', ' ', '.', '-5', '1e3', 'abc', '1.2.3', '5%']) expect(parseInput(text), text).toBeNull()
  })
})

describe('toInput', () => {
  it('shows at most two decimals and no grouping', () => {
    expect(toInput(7981.460001801495)).toBe('7981.46')
    expect(toInput(16524)).toBe('16524')
    expect(toInput(25)).toBe('25')
    expect(toInput(0.004)).toBe('0')
  })
})
