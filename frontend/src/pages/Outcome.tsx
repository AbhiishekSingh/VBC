/**
 * Governance — the outcome sheet.
 *
 * The client's workbook Outcome tab, reproduced live. It exists so the
 * people who built the framework in Excel can see their own arithmetic
 * coming back unchanged, which is how they verify we implemented it and
 * not something adjacent to it.
 */

import { Card, LoadingBlock, Meter, SkeletonTable, toneForScan } from '@/components/ui'
import { csvRows, downloadBlob } from '@/lib/download'
import { useVendorList } from '@/hooks/useVendor'
import { PILLARS } from '@/catalog/generated'
import { DEFAULT_POLICY, applyPolicy, scoreScan } from '@/scoring'
import type { PillarKey } from '@/types/domain'

export default function Outcome() {
  const { vendors, loading } = useVendorList()

  const csv = () => {
    const header = ['Vendor', 'ID', ...PILLARS.map((p) => `${p.key} weighted`), 'Weighted', 'Best', '%', 'Applicable', 'Verdict', 'Policy']
    const rows = vendors.map((v) => {
      const s = scoreScan(v.scan)
      const g = applyPolicy(s, DEFAULT_POLICY)
      return [
        v.name, v.id,
        ...PILLARS.map((p) => s.pillars[p.key as PillarKey].weighted.toFixed(2)),
        s.weighted.toFixed(2), s.best.toFixed(2), s.pct.toFixed(1), `${s.applicable}/${s.total}`,
        g.verdict, g.policyVersion,
      ]
    })
    // Was `"${c}"` with no escaping, so a vendor name containing a double
    // quote broke the column layout of the sheet this page exists to be
    // reconciled against. Audit.tsx already escaped correctly.
    downloadBlob(csvRows([header, ...rows]), 'vbc-outcome-sheet.csv', 'text/csv')
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Governance</div>
        <h2 className="page-h">Outcome sheet</h2>
        <p className="page-sub">
          The workbook Outcome tab, computed live from current data. Pillar subtotals are shown so
          the arithmetic can be checked by hand against the original.
        </p>
      </div>

      <Card
        title="All vendors"
        aside={<button type="button" className="btn" onClick={csv}>Export CSV</button>}
        tight
      >
        <div className="table-wrap is-tall">
          <table className="table">
            <thead>
              <tr>
                <th>Vendor</th>
                {PILLARS.map((p) => (
                  <th key={p.key} className="num" title={`${p.name} · weight ${p.weight}`}>
                    {p.key} ({p.weight})
                  </th>
                ))}
                <th className="num">Weighted</th>
                <th className="num">Best</th>
                <th className="num">60% tol.</th>
                <th>Achievement</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v) => {
                const s = scoreScan(v.scan)
                const g = applyPolicy(s, DEFAULT_POLICY)
                return (
                  <tr key={v.id}>
                    <td>
                      <div className="cell-strong">{v.name}</div>
                      <div className="small muted mono">#{v.id}</div>
                    </td>
                    {PILLARS.map((p) => {
                      const b = s.pillars[p.key as PillarKey]
                      return (
                        <td key={p.key} className="num nums">
                          {b.applicable ? `${b.weighted.toFixed(2)}/${b.max.toFixed(2)}` : '—'}
                          <div className="small muted">{b.G}G {b.Y}Y {b.R}R</div>
                        </td>
                      )
                    })}
                    <td className="num nums"><strong>{s.weighted.toFixed(2)}</strong></td>
                    <td className="num nums">{s.best.toFixed(2)}</td>
                    <td className="num nums muted">{s.tolerance60.toFixed(2)}</td>
                    <td style={{ minWidth: 130 }}>
                      <div className="small nums">{s.pct.toFixed(1)}% · {s.applicable}/{s.total}</div>
                      <Meter pct={s.pct} tone={toneForScan(s.pct, g.gated)} />
                    </td>
                    <td>
                      <span className={`badge b-${g.gated ? 'warn' : s.passed ? 'pass' : 'adverse'}`}>
                        {g.gated ? 'Held' : s.passed ? 'Positive' : 'Negative'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Reading this sheet">
        <p className="small muted">
          Each pillar cell shows weighted over best achievable for that pillar, with the Green /
          Yellow / Red counts beneath. Because Not Applicable parameters leave both sides, a vendor
          with few applicable parameters is measured against a smaller bar — which is why the
          achievement column always states the parameter count alongside the percentage, and why a
          verdict can be Held even at a passing percentage.
        </p>
      </Card>
    </div>
  )
}
