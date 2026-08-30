/**
 * Governance — API cost reference.
 *
 * Real unit prices, each with the derivation that produced it. These come
 * from FileSure's own /v1/account/usage rather than the published rate
 * card, which disagrees: the evaluation report quoted ₹330 for a company
 * unlock and the API reports 22000 paisa. Showing the derivation is how a
 * finance reviewer checks the figure rather than trusting it.
 */

import { useEffect, useState } from 'react'
import { api } from '@/api'
import { Callout, Card, Tile, rupees } from '@/components/ui'
import { COMPANY_UNLOCK_PAISA } from '@/catalog/generated'

type Row = { group: string; item: string; unit: string; source: string }

export default function Costs() {
  const [rows, setRows] = useState<readonly Row[]>([])
  useEffect(() => {
    api.listCostReference().then(setRows)
  }, [])

  const groups = [...new Set(rows.map((r) => r.group))]

  return (
    <div className="stack">
      <div>
        <div className="kicker">Governance</div>
        <h2 className="page-h">API cost reference</h2>
        <p className="page-sub">
          Unit prices with the derivation for each, taken from the providers' own usage endpoints
          rather than their published rate cards.
        </p>
      </div>

      <div className="grid-3">
        <Tile n={rupees(COMPANY_UNLOCK_PAISA + 500)} label="First audit of a company" note="Dominated by the one-time unlock" tone="accent" />
        <Tile n={rupees(500)} label="Repeat audit" note="Inside the one-year unlock window" tone="pass" />
        <Tile n={rupees(COMPANY_UNLOCK_PAISA)} label="Company unlock" note="The cost driver — watch these" tone="warn" />
      </div>

      <Callout kind="warn" title="Unlocks, not call volume, are what costs money">
        In the sample usage data three company unlocks cost more than 1,925 filing downloads. The
        free GET on the unlock path always runs first, so an unlock is never bought for a company
        that already has one.
      </Callout>

      {groups.map((group) => (
        <Card key={group} title={group} tight>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Unit price</th>
                  <th>Derivation</th>
                </tr>
              </thead>
              <tbody>
                {rows.filter((r) => r.group === group).map((r) => (
                  <tr key={r.item}>
                    <td>{r.item}</td>
                    <td className="nums"><strong>{r.unit}</strong></td>
                    <td className="small muted mono">{r.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <Card title="Why the units are never added together">
        <p className="small muted">
          FileSure bills in rupees against a wallet. WhoisXML bills in credits, drawn from separate
          per-product pools — the 500-credit WHOIS History pool is not the 50-credit Domain
          Reputation pool. Screenshots have their own limit of ten. Summing them would produce a
          number with no meaning, so every screen keeps them apart.
        </p>
      </Card>
    </div>
  )
}
