// Geometry of the Campo Verde leaf, drawn in a 200 x 400 box: base at (100, 292), tip at (104, 8), stem below.
// The veins are generated from the outline so they always end inside the leaf.

type Point = [number, number]
type Curve = [Point, Point, Point, Point]

export const LEAF_BOX = '0 0 200 400'
export const LEAF_BOX_ONLY = '0 0 200 300' // without the stem: for the full-screen wipe
export const LEAF_BODY = 'M100 292C30 235 14 110 104 8C176 96 188 226 100 292Z'
export const LEAF_LEFT_HALF = 'M100 292C30 235 14 110 104 8C102 100 98 200 100 292Z'
export const LEAF_MIDRIB = 'M100 292C98 200 102 100 104 8'
export const LEAF_STEM = 'M100 292C100 330 91 362 96 396'

const LEFT_EDGE: Curve = [[100, 292], [30, 235], [14, 110], [104, 8]]
const RIGHT_EDGE: Curve = [[104, 8], [176, 96], [188, 226], [100, 292]]
const MIDRIB: Curve = [[100, 292], [98, 200], [102, 100], [104, 8]]

function bezier([a, b, c, d]: Curve, t: number): Point {
  const u = 1 - t
  return [
    u * u * u * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t * t * t * d[0],
    u * u * u * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t * t * t * d[1],
  ]
}

/** x of a curve at height y (the curves are monotonic in y), by sampling. */
export function xAtY(curve: Curve, y: number): number {
  const samples = Array.from({ length: 241 }, (_, i) => bezier(curve, i / 240))
  for (let i = 1; i < samples.length; i++) {
    const [x0, y0] = samples[i - 1]
    const [x1, y1] = samples[i]
    if ((y0 - y) * (y1 - y) <= 0) return y0 === y1 ? x0 : x0 + ((x1 - x0) * (y - y0)) / (y1 - y0)
  }
  throw new Error(`y = ${y} is outside the curve`)
}

const r = (n: number) => Math.round(n * 10) / 10

/** Side veins as path strings: pairs (left, right) leaving the midrib and curving up towards the edge. */
export function leafVeins(pairs = 7): string[] {
  const paths: string[] = []
  for (let i = 0; i < pairs; i++) {
    const y = 270 - i * 33 // along the midrib, from the base up
    const endY = Math.max(24, y - 50)
    const mx = xAtY(MIDRIB, y)
    for (const edge of [LEFT_EDGE, RIGHT_EDGE]) {
      const ex = mx + (xAtY(edge, endY) - mx) * 0.88
      const dx = ex - mx
      paths.push(
        `M${r(mx)} ${r(y)}C${r(mx + dx * 0.25)} ${r(y - 5)} ${r(mx + dx * 0.7)} ${r(y - 22)} ${r(ex)} ${r(endY + 3)}`,
      )
    }
  }
  return paths
}
