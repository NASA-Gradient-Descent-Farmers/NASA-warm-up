import { useI18n } from '../i18n/index.tsx'
import { MAX_WEIGHT, type WeightSet } from '../lib/weights.ts'
import { OBJECTIVES } from '../lib/types.ts'

const same = (a: WeightSet, b: WeightSet) => OBJECTIVES.every((key) => a[key] === b[key])

interface Props {
  weights: WeightSet
  presets: { sustainability: WeightSet; profit: WeightSet }
  onChange: (weights: WeightSet) => void
}

export function WeightsPanel({ weights, presets, onChange }: Props) {
  const { t } = useI18n()
  return (
    <section className="card" aria-labelledby="weights-title">
      <h3 id="weights-title">{t('planner.weights.title')}</h3>
      <div className="presets" role="group" aria-label={t('planner.weights.title')}>
        <button type="button" aria-pressed={same(weights, presets.sustainability)} onClick={() => onChange(presets.sustainability)}>
          {t('planner.weights.sustainability')}
        </button>
        <button type="button" aria-pressed={same(weights, presets.profit)} onClick={() => onChange(presets.profit)}>
          {t('planner.weights.profit')}
        </button>
      </div>
      {OBJECTIVES.map((key) => (
        <label key={key} className="slider" title={t(`objectives.${key}.hint`)}>
          <span className="slider-head">
            <span>{t(`objectives.${key}.name`)}</span>
            <output>{weights[key]}</output>
          </span>
          <input
            type="range"
            min={0}
            max={MAX_WEIGHT}
            step={1}
            value={weights[key]}
            onChange={(e) => onChange({ ...weights, [key]: Number(e.target.value) })}
          />
        </label>
      ))}
      <p className="note">{t('planner.weights.hint')}</p>
    </section>
  )
}
