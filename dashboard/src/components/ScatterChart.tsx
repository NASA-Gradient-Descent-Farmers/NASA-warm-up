import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n/index.tsx'
import { niceTicks } from '../lib/ticks.ts'
import type { ObjectiveKey, Strategy } from '../lib/types.ts'
import { OBJECTIVES } from '../lib/types.ts'

const MARGIN = { top: 16, right: 20, bottom: 54, left: 72 }
const COLOR_BINS = 4
const HIT_RADIUS = 20 // px: a point is hovered or clicked when the pointer is this close

/** Marker per rotation: shape carries identity, so colour is free for nitrogen lost and CVD readers lose nothing. */
function shapePath(index: number, x: number, y: number, r: number): string {
  switch (index % 4) {
    case 0:
      return `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0z`
    case 1: {
      const h = r * 0.9
      return `M${x - h} ${y - h}h${2 * h}v${2 * h}h${-2 * h}z`
    }
    case 2:
      return `M${x} ${y - r * 1.15}L${x + r * 1.1} ${y + r * 0.85}L${x - r * 1.1} ${y + r * 0.85}z`
    default:
      return `M${x} ${y - r * 1.25}L${x + r * 1.25} ${y}L${x} ${y + r * 1.25}L${x - r * 1.25} ${y}z`
  }
}

function domain(values: number[]): [number, number] {
  const low = Math.min(...values)
  const high = Math.max(...values)
  const pad = high > low ? (high - low) * 0.06 : Math.abs(low) * 0.1 || 1
  return [low - pad, high + pad]
}

interface Props {
  points: Strategy[]
  xKey: ObjectiveKey
  yKey: ObjectiveKey
  colorKey: ObjectiveKey
  rotations: string[]
  /** The plan shown in the side card (highlighted). */
  activeId: number
  isSuggestion: boolean
  onSelect: (id: number) => void
}

export function ScatterChart({ points, xKey, yKey, colorKey, rotations, activeId, isSuggestion, onSelect }: Props) {
  const { t, fmt } = useI18n()
  const wrapper = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const [hoverId, setHoverId] = useState<number | null>(null)

  useEffect(() => {
    const node = wrapper.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const height = width < 520 ? 340 : 440
  const plotW = width - MARGIN.left - MARGIN.right
  const plotH = height - MARGIN.top - MARGIN.bottom

  const layout = useMemo(() => {
    const [x0, x1] = domain(points.map((p) => p.values[xKey]))
    const [y0, y1] = domain(points.map((p) => p.values[yKey]))
    const sx = (v: number) => MARGIN.left + ((v - x0) / (x1 - x0)) * plotW
    const sy = (v: number) => MARGIN.top + (1 - (v - y0) / (y1 - y0)) * plotH
    const colors = points.map((p) => p.values[colorKey])
    const low = Math.min(...colors)
    const high = Math.max(...colors)
    const bin = (v: number) => (high > low ? Math.min(COLOR_BINS - 1, Math.floor(((v - low) / (high - low)) * COLOR_BINS)) : 0)
    const placed = points.map((p) => ({ p, px: sx(p.values[xKey]), py: sy(p.values[yKey]), bin: bin(p.values[colorKey]) }))
    return { x0, x1, y0, y1, sx, sy, low, high, placed, xTicks: niceTicks(x0, x1), yTicks: niceTicks(y0, y1) }
  }, [points, xKey, yKey, colorKey, plotW, plotH])

  const shapeOf = (rotation: string) => Math.max(0, rotations.indexOf(rotation))
  const active = layout.placed.find(({ p }) => p.id === activeId)
  const hover = layout.placed.find(({ p }) => p.id === hoverId)

  const nearest = (clientX: number, clientY: number, svg: SVGSVGElement): number | null => {
    const box = svg.getBoundingClientRect()
    const x = clientX - box.left
    const y = clientY - box.top
    let best: number | null = null
    let bestDistance = HIT_RADIUS
    for (const { p, px, py } of layout.placed) {
      const d = Math.hypot(px - x, py - y)
      if (d < bestDistance) {
        bestDistance = d
        best = p.id
      }
    }
    return best
  }

  const name = (key: ObjectiveKey) => t(`objectives.${key}.name`)
  const label = (key: ObjectiveKey) => `${name(key)} (${t(`objectives.${key}.unit`)})`
  const edge = (k: number) => layout.low + ((layout.high - layout.low) * k) / COLOR_BINS

  return (
    <div className="chart" ref={wrapper}>
      <div className="chart-plot">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={t('planner.chart.ariaLabel', { x: name(xKey), y: name(yKey) })}
          onPointerMove={(e) => setHoverId(nearest(e.clientX, e.clientY, e.currentTarget))}
          onPointerLeave={() => setHoverId(null)}
          onClick={(e) => {
            const id = nearest(e.clientX, e.clientY, e.currentTarget)
            if (id !== null) onSelect(id)
          }}
          style={{ cursor: hoverId === null ? 'default' : 'pointer', touchAction: 'manipulation' }}
        >
          {layout.yTicks.map((v) => (
            <g key={`y${v}`}>
              <line className="grid" x1={MARGIN.left} x2={width - MARGIN.right} y1={layout.sy(v)} y2={layout.sy(v)} />
              <text className="tick" x={MARGIN.left - 10} y={layout.sy(v)} textAnchor="end" dominantBaseline="middle">
                {fmt.tick(v)}
              </text>
            </g>
          ))}
          {layout.xTicks.map((v) => (
            <text key={`x${v}`} className="tick" x={layout.sx(v)} y={height - MARGIN.bottom + 20} textAnchor="middle">
              {fmt.tick(v)}
            </text>
          ))}
          <line className="axis" x1={MARGIN.left} x2={width - MARGIN.right} y1={height - MARGIN.bottom} y2={height - MARGIN.bottom} />
          <text className="axis-label" x={MARGIN.left + plotW / 2} y={height - 10} textAnchor="middle">
            {label(xKey)}
          </text>
          <text
            className="axis-label"
            transform={`translate(16 ${MARGIN.top + plotH / 2}) rotate(-90)`}
            textAnchor="middle"
          >
            {label(yKey)}
          </text>

          {layout.placed.map(({ p, px, py, bin }) => (
            <path
              key={p.id}
              className={`mark seq-${bin + 1}`}
              d={shapePath(shapeOf(p.rotation), px, py, p.id === hoverId ? 6.5 : 5)}
            />
          ))}

          {active && (
            <g pointerEvents="none">
              <circle className="halo" cx={active.px} cy={active.py} r={13} />
              <text
                className="pick-label"
                x={active.px + (active.px > width - 150 ? -18 : 18)}
                y={active.py - 12}
                textAnchor={active.px > width - 150 ? 'end' : 'start'}
              >
                {isSuggestion ? t('planner.chart.pick') : t('planner.chart.yours')}
              </text>
            </g>
          )}
        </svg>

        {hover && (
          <div
            className="tooltip"
            role="status"
            style={{ left: Math.min(hover.px + 14, width - 230), top: Math.max(0, hover.py - 12) }}
          >
            <strong>{t(`rotations.${hover.p.rotation}`)}</strong>
            {OBJECTIVES.map((key) => (
              <div key={key} className="tooltip-row">
                <span>{name(key)}</span>
                <span>
                  {fmt.objective(key, hover.p.values[key])} <small>{t(`objectives.${key}.unit`)}</small>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="legend" aria-hidden="false">
        <div className="legend-group">
          <span className="legend-title">{t('planner.chart.shape')}</span>
          {rotations.map((rotation, i) => (
            <span key={rotation} className="legend-item">
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <path className="mark seq-3" d={shapePath(i, 8, 8, 5)} />
              </svg>
              {t(`rotations.${rotation}`)}
            </span>
          ))}
        </div>
        <div className="legend-group">
          <span className="legend-title">{t('planner.chart.color')}</span>
          {Array.from({ length: COLOR_BINS }, (_, k) => (
            <span key={k} className="legend-item">
              <span className={`swatch seq-${k + 1}`} />
              {fmt.number(edge(k), 0)}–{fmt.number(edge(k + 1), 0)}
            </span>
          ))}
        </div>
      </div>
      <p className="chart-hint">{t('planner.chart.clickHint')}</p>
    </div>
  )
}
