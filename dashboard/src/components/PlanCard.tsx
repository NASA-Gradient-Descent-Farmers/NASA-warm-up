import { useI18n } from '../i18n/index.tsx'
import { goodness, rangeOf } from '../lib/front.ts'
import type { Meta, ObjectiveKey, Strategy, WorldKey } from '../lib/types.ts'
import { OBJECTIVES } from '../lib/types.ts'

interface Props {
  strategy: Strategy
  front: Strategy[]
  meta: Meta
  maximize: Record<ObjectiveKey, boolean>
  world: WorldKey
  isSuggestion: boolean
  /** The suggestion at the original prices, when it differs from this one. */
  baseline: Strategy | null
  onBack: () => void
}

export function PlanCard({ strategy, front, meta, maximize, world, isSuggestion, baseline, onBack }: Props) {
  const { t, fmt } = useI18n()
  const crops = meta.rotations[strategy.rotation] ?? []

  return (
    <aside className="card plan" aria-live="polite">
      <h3>{isSuggestion ? t('planner.plan.title') : t('planner.plan.yourTitle')}</h3>
      {!isSuggestion && (
        <button type="button" className="link" onClick={onBack}>
          {t('planner.plan.back')}
        </button>
      )}

      <dl className="facts">
        <div>
          <dt>{t('planner.plan.rotation')}</dt>
          <dd>{t(`rotations.${strategy.rotation}`)}</dd>
        </div>
        <div>
          <dt>{t('planner.plan.fertilizer')}</dt>
          <dd>
            {[...new Set(crops)].map((crop) => (
              <span key={crop} className="fact-line">
                {t(`crops.${crop}`)}:{' '}
                {t('planner.plan.fertilizerValue', { kg: fmt.number(strategy.nScale * meta.crops[crop].n_kg_ha_at_scale_1) })}
              </span>
            ))}
          </dd>
        </div>
        <div>
          <dt>{t('planner.plan.stover')}</dt>
          <dd>{fmt.percent(strategy.retention)}</dd>
        </div>
      </dl>

      <h4>{t('planner.plan.results', { from: meta.design_years[0], to: meta.design_years[1] })}</h4>
      <ul className="metrics">
        {OBJECTIVES.map((key) => {
          const share = goodness(strategy.values[key], rangeOf(front, key), maximize[key])
          return (
            <li key={key} title={t(`objectives.${key}.hint`)}>
              <div className="metric-head">
                <span>{t(`objectives.${key}.name`)}</span>
                <span className="metric-value">
                  {fmt.objective(key, strategy.values[key])} <small>{t(`objectives.${key}.unit`)}</small>
                </span>
              </div>
              <div className="meter" role="presentation">
                <div className="meter-fill" style={{ width: `${Math.max(3, share * 100)}%` }} />
              </div>
            </li>
          )
        })}
      </ul>
      {baseline && isSuggestion && (
        <p className="note changed" role="status">
          {t('planner.plan.baseline', {
            rotation: t(`rotations.${baseline.rotation}`),
            kg: fmt.number(baseline.nScale * meta.crops.maize.n_kg_ha_at_scale_1),
            stover: fmt.percent(baseline.retention),
          })}
        </p>
      )}
      <p className="note">{t('planner.plan.meter')}</p>
      <p className="note warn">{t(world === 'calibrated' ? 'planner.plan.noteCalibrated' : 'planner.plan.noteDefault')}</p>
    </aside>
  )
}
