// Pareto front and compromise choice: ports of nsga_planner.pareto_front and nsga_planner.choose.
// Checked against the numbers in src/crop_models/NSGA_RESULTS.md by front.test.ts.

import type { ObjectiveKey, Strategy } from './types.ts'

export type Maximize = Record<ObjectiveKey, boolean>
export type Weights = Partial<Record<ObjectiveKey, number>>

/** Objectives closer than this many decimals are ties (nsga_planner.FRONT_DECIMALS). */
export const FRONT_DECIMALS = 9

const roundTo = (value: number, decimals: number) => {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

/** The strategy's objectives as numbers to minimize (maximized ones negated). */
function minimized(strategy: Strategy, keys: ObjectiveKey[], maximize: Maximize, decimals?: number): number[] {
  return keys.map((key) => {
    const value = (maximize[key] ? -1 : 1) * strategy.values[key]
    return decimals === undefined ? value : roundTo(value, decimals) + 0 // + 0 turns -0 into 0
  })
}

function dominates(a: number[], b: number[]): boolean {
  let strictly = false
  for (let i = 0; i < a.length; i++) {
    if (a[i] > b[i]) return false
    if (a[i] < b[i]) strictly = true
  }
  return strictly
}

/**
 * Strategies not dominated by another one on `keys`, in their original order. Objectives are compared after
 * rounding and a strategy that repeats an earlier one on every objective is dropped, like the Python version.
 */
export function paretoFront(
  strategies: Strategy[],
  keys: ObjectiveKey[],
  maximize: Maximize,
  decimals = FRONT_DECIMALS,
): Strategy[] {
  const seen = new Set<string>()
  const unique: { strategy: Strategy; point: number[] }[] = []
  for (const strategy of strategies) {
    const point = minimized(strategy, keys, maximize, decimals)
    const signature = point.join('|')
    if (seen.has(signature)) continue
    seen.add(signature)
    unique.push({ strategy, point })
  }
  // A point that dominates another is lexicographically smaller (the points are distinct), so in that order a
  // point is dominated exactly when a member of the front built so far dominates it, and members never drop out.
  const order = unique.map((_, i) => i).sort((a, b) => {
    const [p, q] = [unique[a].point, unique[b].point]
    for (let i = 0; i < p.length; i++) if (p[i] !== q[i]) return p[i] - q[i]
    return 0
  })
  const front: number[] = []
  for (const i of order) {
    if (!front.some((j) => dominates(unique[j].point, unique[i].point))) front.push(i)
  }
  return front.sort((a, b) => a - b).map((i) => unique[i].strategy)
}

/** Lowest and highest value of an objective over a set of strategies. */
export function rangeOf(strategies: Strategy[], key: ObjectiveKey): [number, number] {
  let low = Infinity
  let high = -Infinity
  for (const { values } of strategies) {
    low = Math.min(low, values[key])
    high = Math.max(high, values[key])
  }
  return [low, high]
}

/**
 * Index of the front member closest to the ideal point in weighted Chebyshev distance (nsga_planner.choose).
 * Each objective with a positive weight is rescaled to [0, 1] over the front (0 = best on the front, 1 = worst)
 * and multiplied by its share of the total weight; the member with the smallest largest weighted shortfall wins,
 * the first one on a tie. All weights zero count as equal weights.
 */
export function choose(front: Strategy[], weights: Weights, maximize: Maximize): number {
  if (front.length === 0) throw new Error('Cannot choose from an empty front')
  let entries = (Object.entries(weights) as [ObjectiveKey, number][]).filter(([, weight]) => weight > 0)
  if (entries.length === 0) entries = (Object.keys(maximize) as ObjectiveKey[]).map((key) => [key, 1])
  const keys = entries.map(([key]) => key)
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0)
  const points = front.map((strategy) => minimized(strategy, keys, maximize))
  const low = keys.map((_, j) => Math.min(...points.map((p) => p[j])))
  const high = keys.map((_, j) => Math.max(...points.map((p) => p[j])))
  let best = 0
  let bestScore = Infinity
  points.forEach((point, i) => {
    let score = 0
    keys.forEach((_, j) => {
      const span = high[j] > low[j] ? high[j] - low[j] : 1
      score = Math.max(score, ((entries[j][1] / total) * (point[j] - low[j])) / span)
    })
    if (score < bestScore) {
      bestScore = score
      best = i
    }
  })
  return best
}

/** Where a value sits between the worst (0) and the best (1) of a range, for a maximized or minimized objective. */
export function goodness(value: number, [low, high]: [number, number], maximize: boolean): number {
  if (high === low) return 1
  const share = (value - low) / (high - low)
  return maximize ? share : 1 - share
}
