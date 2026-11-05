import type { ObjectiveKey, Values } from './types.ts'
import { OBJECTIVES } from './types.ts'

export type WeightSet = Record<ObjectiveKey, number>
export const MAX_WEIGHT = 10

/** Decision weights from the planner (shares summing to 1) as 0-10 sliders: 0.30 becomes 3. */
export function toSliders(weights: Values): WeightSet {
  return Object.fromEntries(OBJECTIVES.map((key) => [key, Math.round((weights[key] ?? 0) * MAX_WEIGHT)])) as WeightSet
}
