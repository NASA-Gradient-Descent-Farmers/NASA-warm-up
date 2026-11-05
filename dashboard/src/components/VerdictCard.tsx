import { useI18n } from '../i18n/index.tsx'
import { verdictKey, type Verdict } from '../lib/coverage.ts'

/** Whether the planner applies where the pin is: always an icon and words, never colour alone. */
export function VerdictCard({ verdict, distanceKm }: { verdict: Verdict | null; distanceKm: number }) {
  const { t, distance } = useI18n()
  if (!verdict) {
    return (
      <div className="verdict pending" role="status">
        <span className="verdict-icon" aria-hidden="true">…</span>
        <p>{t('coverage.pending')}</p>
      </div>
    )
  }
  const key = verdictKey(verdict)
  const km = distance(distanceKm)
  const icon = verdict.status === 'inside' ? '✓' : verdict.status === 'near' ? '≈' : '!'
  return (
    <div className={`verdict ${verdict.status}`} role="status">
      <span className="verdict-icon" aria-hidden="true">
        {icon}
      </span>
      <div>
        <strong>{t(`coverage.${key}.title`)}</strong>
        <p>{t(`coverage.${key}.body`, { km })}</p>
      </div>
    </div>
  )
}
