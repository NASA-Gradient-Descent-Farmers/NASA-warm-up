import { useMemo, useState } from 'react'
import { useI18n } from '../i18n/index.tsx'
import type { Meta, ObjectiveKey, Strategy } from '../lib/types.ts'
import { OBJECTIVES } from '../lib/types.ts'

type SortKey = ObjectiveKey | 'nScale' | 'retention'

interface Props {
  strategies: Strategy[]
  meta: Meta
  maximize: Record<ObjectiveKey, boolean>
  activeId: number
  onSelect: (id: number) => void
}

/** The same strategies as the chart, as a sortable table: the non-visual way to read every value. */
export function FrontTable({ strategies, meta, maximize, activeId, onSelect }: Props) {
  const { t, fmt } = useI18n()
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: 'net_mxn_ha', descending: true })

  const rows = useMemo(() => {
    const value = (s: Strategy) => (sort.key === 'nScale' ? s.nScale : sort.key === 'retention' ? s.retention : s.values[sort.key])
    return [...strategies].sort((a, b) => (sort.descending ? value(b) - value(a) : value(a) - value(b)))
  }, [strategies, sort])

  const maizeDose = meta.crops.maize.n_kg_ha_at_scale_1
  const header = (key: SortKey, text: string) => (
    <th
      key={key}
      scope="col"
      aria-sort={sort.key === key ? (sort.descending ? 'descending' : 'ascending') : 'none'}
      className={key === 'nScale' || key === 'retention' || OBJECTIVES.includes(key as ObjectiveKey) ? 'num' : undefined}
    >
      <button type="button" onClick={() => setSort({ key, descending: sort.key === key ? !sort.descending : maximize[key as ObjectiveKey] ?? true })}>
        {text}
        {sort.key === key ? (sort.descending ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">{t('planner.table.rotation')}</th>
            {header('nScale', t('planner.table.nitrogen'))}
            {header('retention', t('planner.table.stover'))}
            {OBJECTIVES.map((key) => header(key, `${t(`objectives.${key}.name`)} (${t(`objectives.${key}.unit`)})`))}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className={s.id === activeId ? 'active' : undefined} onClick={() => onSelect(s.id)}>
              <th scope="row">{t(`rotations.${s.rotation}`)}</th>
              <td className="num">{fmt.number(s.nScale * maizeDose)}</td>
              <td className="num">{fmt.percent(s.retention)}</td>
              {OBJECTIVES.map((key) => (
                <td key={key} className="num">
                  {fmt.objective(key, s.values[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
