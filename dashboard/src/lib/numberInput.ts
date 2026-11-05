/** Number as typed in a field: at most 2 decimals, no grouping (7981.460001 -> "7981.46"). */
export const toInput = (value: number) => String(Number(value.toFixed(2)))

/** Non-negative number from what was typed ("7,500" and "7 500" are 7500), or null. */
export function parseInput(text: string): number | null {
  const cleaned = text.replace(/[,\s]/g, '')
  if (cleaned === '' || !/^\d*\.?\d*$/.test(cleaned) || cleaned === '.') return null
  return Number(cleaned)
}
