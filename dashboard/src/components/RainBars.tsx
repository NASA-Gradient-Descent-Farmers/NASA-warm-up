import { useState } from 'react'
import { useI18n } from '../i18n/index.tsx'
import { niceTicks } from '../lib/ticks.ts'

const W = 360
const H = 190
const M = { top: 10, right: 6, bottom: 24, left: 36 }
const BAR = 9 // px: thin bars, each at most 24 px
const GAP = 2 // px of surface between the two bars of a month
const R = 3

/** A bar that grows from the baseline with a rounded top and a square foot. */
function barPath(x: number, top: number, bottom: number): string {
  const height = bottom - top
  if (height <= 0) return ''
  const r = Math.min(R, height)
  return `M${x} ${bottom}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + BAR - r}Q${x + BAR} ${top} ${x + BAR} ${top + r}V${bottom}Z`
}

interface Props {
  here: number[]
  reference: number[]
}

/** Rain by month at the farmer's pin (series 1) and at the modeled site (series 2). */
export function RainBars({ here, reference }: Props) {
  const { t, fmt } = useI18n()
  const [hover, setHover] = useState<number | null>(null)
  const top = Math.max(...here, ...reference)
  const ticks = niceTicks(0, top, 4)
  const ceiling = Math.max(top, ticks[ticks.length - 1])
  const plotW = W - M.left - M.right
  const plotH = H - M.top - M.bottom
  const y = (v: number) => M.top + plotH - (v / ceiling) * plotH
  const group = plotW / 12

  return (
    <div className="rain">
      <div className="rain-legend">
        <span>
          <i className="swatch s1" />
          {t('climate.you')}
        </span>
        <span>
          <i className="swatch s2" />
          {t('climate.model')}
        </span>
      </div>
      <div className="rain-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t('climate.chartLabel')} onPointerLeave={() => setHover(null)}>
          {ticks.map((v) => (
            <g key={v}>
              <line className="rain-grid" x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} />
              <text className="rain-tick" x={M.left - 6} y={y(v)} textAnchor="end" dominantBaseline="middle">
                {fmt.number(v)}
              </text>
            </g>
          ))}
          {here.map((value, month) => {
            const left = M.left + group * month + (group - (2 * BAR + GAP)) / 2
            return (
              <g key={month}>
                <path className="bar s1" d={barPath(left, y(value), y(0))} />
                <path className="bar s2" d={barPath(left + BAR + GAP, y(reference[month]), y(0))} />
                <text className="rain-month" x={M.left + group * (month + 0.5)} y={H - 7} textAnchor="middle">
                  {fmt.monthShort(month).slice(0, 3)}
                </text>
                <rect
                  className="rain-hit"
                  x={M.left + group * month}
                  y={M.top}
                  width={group}
                  height={plotH}
                  onPointerEnter={() => setHover(month)}
                  onPointerMove={() => setHover(month)}
                />
              </g>
            )
          })}
        </svg>
        {hover !== null && (
          <div className="rain-tip" role="status" style={{ left: `${((M.left + group * (hover + 0.5)) / W) * 100}%` }}>
            <strong>{fmt.monthLong(hover)}</strong>
            <span>
              <i className="swatch s1" />
              {t('climate.you')}: {fmt.number(here[hover])} mm
            </span>
            <span>
              <i className="swatch s2" />
              {t('climate.model')}: {fmt.number(reference[hover])} mm
            </span>
          </div>
        )}
      </div>
      <details className="rain-table">
        <summary>{t('climate.table')}</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">{t('climate.month')}</th>
              <th scope="col" className="num">
                {t('climate.you')} (mm)
              </th>
              <th scope="col" className="num">
                {t('climate.model')} (mm)
              </th>
            </tr>
          </thead>
          <tbody>
            {here.map((value, month) => (
              <tr key={month}>
                <th scope="row">{fmt.monthLong(month)}</th>
                <td className="num">{fmt.number(value)}</td>
                <td className="num">{fmt.number(reference[month])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}
