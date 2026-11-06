// The exact five-objective Pareto front of the whole strategy lattice for a set of economics, with a small cache.

import { paretoFront, type Maximize } from './front.ts'
import { Planner } from './planner.ts'
import type { Economics, GridWorld, Meta, ObjectiveKey, Strategy } from './types.ts'
import { OBJECTIVES } from './types.ts'

const CACHE_PER_WORLD = 6
const cache = new WeakMap<GridWorld, Map<string, Strategy[]>>()

/**
 * Score every rotation x fertilizer scale x stover retention of the lattice with `economics` and keep the
 * non-dominated ones on all five objectives. Strategy ids are lattice positions, so they do not depend on prices.
 * Fronts on fewer objectives are subsets of this one (see `frontOn`).
 */
export function exactFront(
  world: GridWorld,
  economics: Economics,
  { lattice, planner }: Pick<Meta, 'lattice' | 'planner'>,
  maximize: Maximize,
): Strategy[] {
  const key = JSON.stringify(economics)
  let perWorld = cache.get(world)
  if (!perWorld) cache.set(world, (perWorld = new Map()))
  const hit = perWorld.get(key)
  if (hit) return hit
  const all = new Planner(world, economics, planner.cvar_share).bruteForce(lattice.n_scale_steps, lattice.retention_steps)
  const front = paretoFront(all, [...OBJECTIVES], maximize, planner.front_decimals)
  perWorld.set(key, front)
  if (perWorld.size > CACHE_PER_WORLD) perWorld.delete(perWorld.keys().next().value!)
  return front
}

/** The front on some of the objectives, from the five-objective front (a strategy that is non-dominated on a
 *  subset of objectives is non-dominated on all of them, up to ties). */
export function frontOn(exact: Strategy[], keys: ObjectiveKey[], maximize: Maximize, decimals: number): Strategy[] {
  return keys.length === OBJECTIVES.length ? exact : paretoFront(exact, keys, maximize, decimals)
}

export const sameEconomics = (a: Economics, b: Economics) => JSON.stringify(a) === JSON.stringify(b)
