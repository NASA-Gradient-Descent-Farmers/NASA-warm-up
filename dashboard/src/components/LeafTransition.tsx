import { useEffect, useRef } from 'react'
import { LeafWipe } from './Leaf.tsx'

export interface WipeOrigin {
  x: number
  y: number
}

interface Props {
  origin: WipeOrigin
  /** Called once the leaf covers the whole screen: swap the page underneath here. */
  onCovered: () => void
  onDone: () => void
}

const LEAF_HEIGHT = 150 // px of the leaf before it is scaled (its box is 100 x 150)
const GROW_MS = 1000
const FADE_MS = 700

/**
 * A leaf unfurls from the clicked point, spinning as it grows until it fills the screen (its veins become
 * huge), the page changes underneath, and the leaf turns on and fades away.
 */
export function LeafTransition({ origin, onCovered, onDone }: Props) {
  const veil = useRef<HTMLDivElement>(null)
  const leaf = useRef<HTMLDivElement>(null)
  const callbacks = useRef({ onCovered, onDone })
  useEffect(() => {
    callbacks.current = { onCovered, onDone } // the animation's callbacks always see the latest ones
  })

  useEffect(() => {
    const root = veil.current
    const el = leaf.current
    if (!root || !el) return
    let cancelled = false
    const fill = (6 * Math.max(window.innerWidth, window.innerHeight)) / LEAF_HEIGHT // covers the screen from any corner
    const centre = 'translate(-50%, -50%)'
    const grow = el.animate(
      [
        { transform: `${centre} rotate(-65deg) scale(0.05)` },
        { transform: `${centre} rotate(8deg) scale(${fill})` },
      ],
      { duration: GROW_MS, easing: 'cubic-bezier(0.65, 0.02, 0.2, 1)', fill: 'forwards' },
    )
    const animations = [grow]
    grow.finished
      .then(() => {
        if (cancelled) return
        callbacks.current.onCovered()
        const turn = el.animate(
          [
            { transform: `${centre} rotate(8deg) scale(${fill})` },
            { transform: `${centre} rotate(38deg) scale(${fill * 1.5})` },
          ],
          { duration: FADE_MS, easing: 'ease-in', fill: 'forwards' },
        )
        const fade = root.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_MS, easing: 'ease-in', fill: 'forwards' })
        animations.push(turn, fade)
        return fade.finished
      })
      .then(() => {
        if (!cancelled) callbacks.current.onDone()
      })
      .catch(() => {
        // cancelled (unmounted or React strict-mode re-run): nothing to finish
      })
    return () => {
      cancelled = true
      animations.forEach((a) => a.cancel())
    }
  }, [])

  return (
    <div className="leaf-veil" ref={veil} role="presentation">
      <div className="leaf-wipe" ref={leaf} style={{ left: origin.x, top: origin.y }}>
        <LeafWipe />
      </div>
    </div>
  )
}
