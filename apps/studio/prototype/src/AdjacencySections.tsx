import type { ReactNode } from 'react';
import type { Topology } from './gateway';
import { Badge, Empty, Section } from './ui';
import { RouterIncidenceMatrix } from './RouterIncidenceMatrix';
import { cappedClass } from './format';

/** Declared connection resources folded into router pairs. A pair says two
 *  routers share a channel or a shared-wire tap; it is not a permitted flow. */
export function RouterAdjacencySections({ topology, banner }: { topology: Topology | null; banner?: ReactNode }) {
  if (!topology) return <>{banner}<Empty title="No topology document">Adjacency needs a declared router and channel list.</Empty></>;
  const pairs = new Map<string, { a: number; b: number; width: number; latency: number; directed: number }>();
  for (const channel of topology.channels) {
    const key = channel.src_router < channel.dst_router ? `${channel.src_router}-${channel.dst_router}` : `${channel.dst_router}-${channel.src_router}`;
    const current = pairs.get(key) ?? { a: Math.min(channel.src_router, channel.dst_router), b: Math.max(channel.src_router, channel.dst_router), width: channel.width_bits, latency: channel.latency_cycles, directed: 0 };
    pairs.set(key, { ...current, directed: current.directed + 1 });
  }
  const rows = [...pairs.values()];
  const degree = new Map<number, number>();
  for (const row of rows) { degree.set(row.a, (degree.get(row.a) ?? 0) + 1); degree.set(row.b, (degree.get(row.b) ?? 0) + 1); }
  const degrees = [...new Set(degree.values())].sort((a, b) => a - b);
  return <>
    {banner}
    <Section title="Connection incidence matrix" actions={<Badge>declared structure</Badge>}>
      <RouterIncidenceMatrix topology={topology} />
    </Section>
    <Section title="Router adjacency from declared channels" actions={<Badge>{rows.length} undirected pairs</Badge>}>
      {rows.length ? <>
        <div className={`table-scroll${cappedClass(rows.length)}`}><table><thead><tr><th>Router pair</th><th>Channels</th><th>Width</th><th>Latency</th></tr></thead><tbody>
          {rows.map(row => <tr key={`${row.a}-${row.b}`}><th className="mono">R{row.a} ↔ R{row.b}</th><td className="numeric">{row.directed}</td><td className="numeric">{row.width} b</td><td className="numeric">{row.latency} cyc</td></tr>)}
        </tbody></table></div>
        <p className="meta-line">Router degree: {degrees.join(', ')}.</p>
      </> : <p className="meta-line">No directed channels are declared.</p>}
    </Section>
  </>;
}
