import type { ReactNode } from 'react';
import { Badge, Empty, Section } from './ui';

export type CoverageRow = { key: string; declared: number; seats: number };

/** Declared against materialised, per classification. A share bar is a
 *  proportion of materialised seats, not a performance or coverage claim. */
export function SeatCoverageTable({ rows, total, title = 'Seat coverage', declaredLabel = 'Declared agents', seatsLabel = 'Endpoint seats', emptyTitle, emptyBody, actions }: {
  rows: CoverageRow[];
  total: number;
  title?: string;
  declaredLabel?: string;
  seatsLabel?: string;
  emptyTitle?: string;
  emptyBody?: ReactNode;
  actions?: ReactNode;
}) {
  return <Section title={title} actions={<>{actions}<Badge>{total} seat{total === 1 ? '' : 's'}</Badge></>}>
    {rows.length ? <div className="table-scroll"><table><thead><tr><th>Classification</th><th>{declaredLabel}</th><th>{seatsLabel}</th><th>Share of seats</th></tr></thead><tbody>
      {rows.map(row => {
        const share = total ? Math.round(row.seats / total * 100) : 0;
        return <tr key={row.key}><th>{row.key}</th><td className="numeric">{row.declared}</td><td className="numeric">{row.seats}</td><td><div className="coverage-share"><div className="metric-bar"><span style={{ width: `${share}%` }} /></div><span className="mono">{share}%</span></div></td></tr>;
      })}
    </tbody></table></div> : <Empty title={emptyTitle ?? 'Nothing materialised in this revision'}>{emptyBody ?? 'Seats appear after the topology attachment is compiled.'}</Empty>}
  </Section>;
}
