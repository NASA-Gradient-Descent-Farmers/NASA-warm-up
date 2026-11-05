import { useI18n } from '../i18n/index.tsx'
import type { Economics, Meta } from '../lib/types.ts'
import { NumberField } from './NumberField.tsx'

interface Props {
  meta: Meta
  economics: Economics
  edited: boolean
  onChange: (economics: Economics) => void
}

export function PricesPanel({ meta, economics, edited, onChange }: Props) {
  const { t, fmt } = useI18n()
  const crops = [...new Set(meta.rotation_order.flatMap((rotation) => meta.rotations[rotation]))]
  const invalid = t('planner.prices.invalid')
  const badge = (key: string) =>
    meta.placeholders.includes(key) ? (
      <span className="badge placeholder">{t('planner.prices.placeholder')}</span>
    ) : (
      <span className="badge sourced">{t('planner.prices.siap')}</span>
    )
  const setPrice = (crop: string, value: number) => onChange({ ...economics, prices: { ...economics.prices, [crop]: value } })
  const setCost = (crop: string, value: number) => onChange({ ...economics, other_costs: { ...economics.other_costs, [crop]: value } })

  return (
    <section className="card prices" aria-labelledby="prices-title">
      <h3 id="prices-title">{t('planner.prices.title')}</h3>
      <p className="note first">{t('planner.prices.intro')}</p>

      <table className="price-table">
        <thead>
          <tr>
            <th scope="col">{t('planner.prices.crop')}</th>
            <th scope="col">
              {t('planner.prices.grain')} {badge('prices')}
            </th>
            <th scope="col">
              {t('planner.prices.cost')} {badge('other_costs')}
            </th>
          </tr>
        </thead>
        <tbody>
          {crops.map((crop) => (
            <tr key={crop}>
              <th scope="row">{t(`crops.${crop}`)}</th>
              <td>
                <NumberField
                  value={economics.prices[crop]}
                  onChange={(v) => setPrice(crop, v)}
                  label={`${t(`crops.${crop}`)}: ${t('planner.prices.grain')}`}
                  invalidMessage={invalid}
                />
              </td>
              <td>
                <NumberField
                  value={economics.other_costs[crop]}
                  onChange={(v) => setCost(crop, v)}
                  label={`${t(`crops.${crop}`)}: ${t('planner.prices.cost')}`}
                  invalidMessage={invalid}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <ul className="siap-hints">
        {crops.map((crop) => {
          const siap = meta.siap_prices[crop]
          if (!siap) return null
          return (
            <li key={crop}>
              <span>
                {t(`crops.${crop}`)}:{' '}
                {t('planner.prices.siapHint', {
                  year: siap.latest_year,
                  latest: fmt.number(siap.latest_mxn_t),
                  median: fmt.number(siap.median_3y_mxn_t),
                })}
              </span>{' '}
              <button
                type="button"
                className="link"
                onClick={() => setPrice(crop, siap.latest_mxn_t)}
                aria-label={`${t(`crops.${crop}`)}: ${t('planner.prices.useLatest', { value: fmt.number(siap.latest_mxn_t) })}`}
              >
                {t('planner.prices.useLatest', { value: fmt.number(siap.latest_mxn_t) })}
              </button>
            </li>
          )
        })}
      </ul>

      <div className="price-pair">
        <label>
          <span>
            {t('planner.prices.nPrice')} {badge('n_price')}
          </span>
          <NumberField
            value={economics.n_price}
            onChange={(v) => onChange({ ...economics, n_price: v })}
            label={t('planner.prices.nPrice')}
            invalidMessage={invalid}
          />
        </label>
        <label>
          <span>
            {t('planner.prices.stoverPrice')} {badge('stover_price')}
          </span>
          <NumberField
            value={economics.stover_price}
            onChange={(v) => onChange({ ...economics, stover_price: v })}
            label={t('planner.prices.stoverPrice')}
            invalidMessage={invalid}
          />
        </label>
      </div>

      <button type="button" className="reset" disabled={!edited} onClick={() => onChange(meta.economics)}>
        {t('planner.prices.reset')}
      </button>
    </section>
  )
}
