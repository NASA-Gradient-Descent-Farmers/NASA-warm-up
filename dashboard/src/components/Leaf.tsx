import { useId, useMemo, type CSSProperties } from 'react'
import { LEAF_BODY, LEAF_BOX, LEAF_BOX_ONLY, LEAF_LEFT_HALF, LEAF_MIDRIB, LEAF_STEM, leafVeins } from '../lib/leaf.ts'

/** The hero leaf: a stem that draws itself, a blade that unfurls from its base, then veins that trace in. */
export function LeafHero() {
  const gradient = useId().replace(/:/g, '')
  const veins = useMemo(() => leafVeins(), [])
  return (
    <svg className="leaf-hero" viewBox={LEAF_BOX} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={gradient} x1="0.1" y1="1" x2="0.35" y2="0">
          <stop offset="0" stopColor="#14502e" />
          <stop offset="0.5" stopColor="#2f8f4c" />
          <stop offset="1" stopColor="#a9dc6c" />
        </linearGradient>
      </defs>
      <g className="leaf-sway">
        <path className="leaf-stem" d={LEAF_STEM} pathLength={1} />
        <g className="leaf-grow">
          <path d={LEAF_BODY} fill={`url(#${gradient})`} />
          <path className="leaf-shade" d={LEAF_LEFT_HALF} />
          {veins.map((d, i) => (
            <path key={i} className="leaf-vein" d={d} pathLength={1} style={{ '--i': Math.floor(i / 2) } as CSSProperties} />
          ))}
          <path className="leaf-midrib" d={LEAF_MIDRIB} pathLength={1} />
        </g>
      </g>
    </svg>
  )
}

/** A small flat leaf for the falling-leaves layer and the logo. */
export function LeafMark({ className, style }: { className?: string; style?: CSSProperties }) {
  return (
    <svg className={className} style={style} viewBox={LEAF_BOX_ONLY} aria-hidden="true" focusable="false">
      <path d={LEAF_BODY} fill="currentColor" />
      <path d={LEAF_MIDRIB} fill="none" stroke="var(--leaf-vein, rgba(255,255,255,.55))" strokeWidth="8" strokeLinecap="round" />
    </svg>
  )
}

/** The leaf that sweeps across the screen: flat green, veins in a lighter green (they become huge as it grows). */
export function LeafWipe() {
  const gradient = useId().replace(/:/g, '')
  const veins = useMemo(() => leafVeins(), [])
  return (
    <svg className="leaf-wipe-art" viewBox={LEAF_BOX_ONLY} aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id={gradient} cx="0.5" cy="0.62" r="0.7">
          <stop offset="0" stopColor="#2a8c4f" />
          <stop offset="1" stopColor="#12392a" />
        </radialGradient>
      </defs>
      <path d={LEAF_BODY} fill={`url(#${gradient})`} />
      {veins.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="rgba(190,235,140,.28)" strokeWidth="2.6" strokeLinecap="round" />
      ))}
      <path d={LEAF_MIDRIB} fill="none" stroke="rgba(190,235,140,.4)" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}
