import { useDeferredValue, useMemo, useState } from 'react'
import { FrontTable } from '../components/FrontTable.tsx'
import { PlanCard } from '../components/PlanCard.tsx'
import { PricesPanel } from '../components/PricesPanel.tsx'
import { ScatterChart } from '../components/ScatterChart.tsx'
import { WeightsPanel } from '../components/WeightsPanel.tsx'
import { useI18n } from '../i18n/index.tsx'
import { choose } from '../lib/front.ts'
import { exactFront, frontOn, sameEconomics } from '../lib/scenario.ts'
import type { DashboardData, Economics, ObjectiveKey, Strategy, WorldKey } from '../lib/types.ts'
import { OBJECTIVES, WORLDS } from '../lib/types.ts'
import { toSliders, type WeightSet } from '../lib/weights.ts'

const sameStrategy = (a: Strategy, b: Strategy) => a.rotation === b.rotation && a.nScale === b.nScale && a.retention === b.retention

export function PlannerScreen({ data }: { data: DashboardData }) {
  const { t, fmt } = useI18n()
  const { meta, grids, maximize } = data
  const presets = useMemo(
    () => ({ sustainability: toSliders(meta.weights.sustainability_first), profit: toSliders(meta.weights.profit_first) }),
    [meta],
  )

  const [world, setWorld] = useState<WorldKey>('calibrated')
  const [weights, setWeights] = useState<WeightSet>(presets.sustainability)
  const [economics, setEconomics] = useState<Economics>(meta.economics)
  const [xKey, setXKey] = useState<ObjectiveKey>('c_input_t_ha')
  const [yKey, setYKey] = useState<ObjectiveKey>('net_mxn_ha')
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [pickedId, setPickedId] = useState<number | null>(null)

  // Typing in a price field stays responsive: the strategies are re-scored from a slightly delayed copy.
  const scored = useDeferredValue(economics)
  const stale = scored !== economics
  const edited = !sameEconomics(scored, meta.economics)

  // The trade-off curve is over the objectives that matter (weight above 0); all of them if none is chosen.
  const mattering = OBJECTIVES.filter((key) => weights[key] > 0)
  const keyList = (mattering.length > 0 ? mattering : OBJECTIVES).join(',')
  const keys = useMemo(() => keyList.split(',') as ObjectiveKey[], [keyList])

  const exact = useMemo(() => exactFront(grids[world], scored, meta.lattice, maximize), [grids, world, scored, meta, maximize])
  const front = useMemo(() => frontOn(exact, keys, maximize), [exact, keys, maximize])
  const suggested = front[choose(front, weights, maximize)]
  const picked = pickedId === null ? undefined : front.find((s) => s.id === pickedId)
  const shown = picked ?? suggested

  // What the same weights would have suggested at the original prices, to show what the new figures changed.
  const baseline = useMemo(() => {
    if (!edited) return null
    const original = frontOn(exactFront(grids[world], meta.economics, meta.lattice, maximize), keys, maximize)
    const before = original[choose(original, weights, maximize)]
    return sameStrategy(before, suggested) ? null : before
  }, [edited, grids, world, meta, maximize, keys, weights, suggested])

  const changeWeights = (next: WeightSet) => {
    setWeights(next)
    setPickedId(null)
  }
  const changeWorld = (next: WorldKey) => {
    setWorld(next)
    setPickedId(null)
  }
  const rotations = meta.rotation_order
  const scoredCount = rotations.length * (meta.lattice.n_scale_steps + 1) * (meta.lattice.retention_steps + 1)

  const axisSelect = (id: string, labelKey: string, value: ObjectiveKey, set: (key: ObjectiveKey) => void) => (
    <label className="field" htmlFor={id}>
      <span>{t(labelKey)}</span>
      <select id={id} value={value} onChange={(e) => set(e.target.value as ObjectiveKey)}>
        {OBJECTIVES.map((key) => (
          <option key={key} value={key}>
            {t(`objectives.${key}.name`)}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <section className="planner" aria-labelledby="planner-title">
      <div className="planner-head">
        <h2 id="planner-title">{t('planner.title')}</h2>
        <p className="lede">{t('planner.intro')}</p>
      </div>

      <div className="planner-grid">
        <div className="controls">
          <section className="card" aria-labelledby="world-title">
            <h3 id="world-title">{t('planner.world.label')}</h3>
            <div className="segmented stacked" role="group" aria-label={t('planner.world.label')}>
              {WORLDS.map((key) => (
                <button key={key} type="button" aria-pressed={world === key} onClick={() => changeWorld(key)}>
                  {t(`planner.world.${key}.name`)}
                </button>
              ))}
            </div>
            <p className="note">{t(`planner.world.${world}.note`)}</p>
          </section>
          <WeightsPanel weights={weights} presets={presets} onChange={changeWeights} />
          <PricesPanel meta={meta} economics={economics} edited={!sameEconomics(economics, meta.economics)} onChange={setEconomics} />
        </div>

        <div className={`main card${stale ? ' stale' : ''}`} aria-busy={stale}>
          <div className="main-head">
            <p className="count">{t('planner.chart.count', { shown: fmt.number(front.length), total: fmt.number(scoredCount) })}</p>
            <div className="segmented small" role="group" aria-label={t('planner.chart.view')}>
              <button type="button" aria-pressed={view === 'chart'} onClick={() => setView('chart')}>
                {t('planner.chart.chart')}
              </button>
              <button type="button" aria-pressed={view === 'table'} onClick={() => setView('table')}>
                {t('planner.chart.table')}
              </button>
            </div>
          </div>
          {view === 'chart' ? (
            <>
              <div className="axes">
                {axisSelect('x-axis', 'planner.chart.x', xKey, setXKey)}
                {axisSelect('y-axis', 'planner.chart.y', yKey, setYKey)}
              </div>
              <ScatterChart
                points={front}
                xKey={xKey}
                yKey={yKey}
                colorKey="n_loss_kg_ha"
                rotations={rotations}
                activeId={shown.id}
                isSuggestion={!picked}
                onSelect={setPickedId}
              />
            </>
          ) : (
            <FrontTable strategies={front} meta={meta} maximize={maximize} activeId={shown.id} onSelect={setPickedId} />
          )}
        </div>

        <PlanCard
          strategy={shown}
          front={front}
          meta={meta}
          maximize={maximize}
          world={world}
          isSuggestion={!picked}
          baseline={baseline}
          onBack={() => setPickedId(null)}
        />
      </div>
    </section>
  )
}
