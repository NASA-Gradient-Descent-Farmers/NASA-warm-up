import { useI18n } from '../i18n/index.tsx'
import type { ClimateState } from '../hooks/useCoverage.ts'
import { RainBars } from './RainBars.tsx'

export function ClimateCard({ climate, onRetry }: { climate: ClimateState; onRetry: () => void }) {
  const { t, fmt } = useI18n()
  return (
    <section className="climate" aria-labelledby="climate-title" aria-busy={climate.state === 'loading'}>
      <h2 id="climate-title">{t('climate.title')}</h2>
      <p className="climate-source">{t('climate.source')}</p>

      {climate.state === 'loading' && <p className="climate-status">{t('climate.loading')}</p>}
      {climate.state === 'error' && (
        <p className="climate-status">
          {t('climate.error', { message: climate.message })}{' '}
          <button type="button" className="link" onClick={onRetry}>
            {t('climate.retry')}
          </button>
        </p>
      )}
      {climate.state === 'ready' && (
        <>
          <dl className="climate-stats">
            <div>
              <dt>{t('climate.rain')}</dt>
              <dd>
                {fmt.number(climate.here.rainAnnualMm)} <small>mm</small>
              </dd>
              <dd className="delta">{t('climate.vs', { delta: `${fmt.signed(climate.comparison.rainDiffShare * 100)}%` })}</dd>
            </div>
            <div>
              <dt>{t('climate.temp')}</dt>
              <dd>
                {fmt.number(climate.here.meanTempC, 1)} <small>°C</small>
              </dd>
              <dd className="delta">{t('climate.vs', { delta: `${fmt.signed(climate.comparison.meanTempDiffC, 1)} °C` })}</dd>
            </div>
            <div>
              <dt>{t('climate.cold')}</dt>
              <dd>
                {fmt.number(climate.here.lowestMinC, 1)} <small>°C</small>
              </dd>
              <dd className="delta">{t('climate.vs', { delta: `${fmt.signed(climate.comparison.lowestMinDiffC, 1)} °C` })}</dd>
            </div>
          </dl>
          <p className="climate-note">{t('climate.coldNote')}</p>
          <h3>{t('climate.chartTitle')}</h3>
          <RainBars here={climate.here.rainMonthlyMm} reference={climate.reference.rainMonthlyMm} />
        </>
      )}
    </section>
  )
}
