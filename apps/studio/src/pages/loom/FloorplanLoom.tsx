import { useMemo, type ReactElement, type ReactNode } from 'react';
import { fabricModelFromTopology } from '../../fabricLayout';
import { additiveGesture } from '../../util';
import { channelAdjacency, type LoomData } from './data';
import { edgeId, loomIdText, pickId } from './selection';
import type { LoomSelectionStore } from './selectionStore';
import { ExtensionPoint, Kv, Panes, RailSection, From, SummaryStrip } from './parts';

/** Overlays a physical view normally offers. Only placement backed by the
 *  certified coordinates exists; the rest name their artifact. */
const OVERLAYS: { id: string; label: string; available: boolean; needs: string }[] = [
  { id: 'placement', label: 'Router placement & channel adjacency', available: true, needs: '' },
  { id: 'lengths', label: 'Link lengths (mm)', available: false, needs: 'a physical-link row per channel; absent on revisions that carry no placement' },
  { id: 'congestion', label: 'Routing congestion (GRC density)', available: false, needs: 'a placement-and-routing congestion report' },
  { id: 'slack', label: 'Wire delay slack (WNS / TNS)', available: false, needs: 'a static-timing-analysis report' },
  { id: 'clock', label: 'Clock tree distribution', available: false, needs: 'a clock-tree-synthesis artifact' },
  { id: 'thermal', label: 'Thermal / power density (TDP)', available: false, needs: 'a power-density map' },
];

const CELL = 88;
const MARGIN = 52;

function stats(values: number[]): { min: number; max: number; mean: number } | null {
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { min, max, mean: values.reduce((a, b) => a + b, 0) / values.length };
}

export default function FloorplanLoom({ data, sel, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  problems?: ReactNode;
}): ReactElement {
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;

  const model = useMemo(
    () => (topology ? fabricModelFromTopology(topology) : null),
    [topology],
  );
  const edges = useMemo(() => channelAdjacency(topology), [topology]);

  // An adjacency is a property of two routers, so its id is the ascending pair
  // rather than a row position: it is the same id whichever end you clicked.
  const pair = pickId(sel.selection, 'edge');
  const edge = pair
    ? edges.find((e) => e.a === pair.src && e.b === pair.dst) ?? null
    : null;
  const withLength = useMemo(
    () => edges.filter((e) => e.lengthMm != null),
    [edges],
  );
  const lengths = useMemo(
    () => withLength.map((e) => e.lengthMm).filter((v): v is number => v != null),
    [withLength],
  );
  const latencies = useMemo(
    () => (topology?.channels ?? []).map((c) => c.latency_cycles),
    [topology],
  );
  const lengthStats = stats(lengths);
  const latencyStats = stats(latencies);

  if (!topology || !model) {
    return (
      <Panes
        stage={
          <ExtensionPoint
            title="No placement to draw"
            needs={data.revisionId
              ? 'a materialized TopologyView; router coordinates and physical links only exist once the design compiles'
              : 'a compiled revision'}
          />
        }
      />
    );
  }

  const W = Math.max(1, model.cols) * CELL + MARGIN * 2;
  const H = Math.max(1, model.rows) * CELL + MARGIN * 2;
  const pos = (id: number): { x: number; y: number } | null => {
    const n = model.nodes.find((x) => x.id === id);
    if (!n) return null;
    return { x: MARGIN + n.col * CELL + CELL / 2, y: MARGIN + n.row * CELL + CELL / 2 };
  };

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Placement overlays"
            note="An overlay renders only from its backing artifact."
          >
            <ul className="loom-checks">
              {OVERLAYS.map((o) => {
                const available = o.id === 'lengths'
                  ? edges.some((e) => e.lengthMm != null)
                  : o.available;
                return (
                  <li key={o.id} className={available ? 'on' : 'off'}>
                    <input
                      type="checkbox"
                      checked={available}
                      disabled
                      id={`fp-${o.id}`}
                    />
                    <label htmlFor={`fp-${o.id}`}>{o.label}</label>
                    {!available && <em>needs {o.needs}</em>}
                  </li>
                );
              })}
            </ul>
          </RailSection>

          <RailSection title="Fabric geometry">
            <From origin="DERIVED" artifact="topology" />
            <Kv label="routers placed" value={String(model.counts.routers)} mono />
            <Kv label="channel adjacencies" value={String(edges.length)} mono />
            <Kv label="physical links" value={String(topology.physical_links.length)} mono />
            <Kv label="link length min" value={lengthStats ? `${lengthStats.min} mm` : '—'} mono />
            <Kv label="link length mean" value={lengthStats ? `${lengthStats.mean.toFixed(1)} mm` : '—'} mono />
            <Kv label="link length max" value={lengthStats ? `${lengthStats.max} mm` : '—'} mono />
            <Kv label="channel latency min" value={latencyStats ? `${latencyStats.min} cyc` : '—'} mono />
            <Kv label="channel latency max" value={latencyStats ? `${latencyStats.max} cyc` : '—'} mono />
          </RailSection>

          <RailSection title="Not derivable here">
            <p className="muted">
              Die outline, metal stack, area and power figures are physical-design
              outputs. The compiler views carry coordinates and channel adjacency
              (plus lengths where they exist), so no area or timing number appears
              on this page.
            </p>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Placement', v: 'CERTIFIED COORDINATES', tone: 'ok' },
            { k: 'Grid', v: `${model.cols} × ${model.rows}`, tone: 'info' },
            { k: 'Adjacencies', v: String(edges.length) },
            { k: 'Lengths carried', v: lengthStats ? `${withLength.length} links` : 'none', tone: lengthStats ? undefined : 'warn' },
            { k: 'Latency range', v: latencyStats ? `${latencyStats.min}–${latencyStats.max} cyc` : '—' },
          ]} />

          <div className="loom-table-wrap">
            <svg viewBox={`0 0 ${W} ${H}`} className="canvas" role="img"
                 aria-label={`Placement: ${model.counts.routers} routers, ${edges.length} channel adjacencies`}>
              {edges.map((e) => {
                const pa = pos(e.a);
                const pb = pos(e.b);
                if (!pa || !pb) return null;
                const na = model.nodes.find((n) => n.id === e.a);
                const nb = model.nodes.find((n) => n.id === e.b);
                const jump = na && nb
                  && Math.max(Math.abs(na.col - nb.col), Math.abs(na.row - nb.row)) > 1;
                const on = pair?.src === e.a && pair?.dst === e.b;
                return (
                  <line
                    key={`${e.a}-${e.b}`}
                    x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                    className={`loom-flink${jump ? ' loom-flink-long' : ''}${on ? ' on' : ''}`}
                    onClick={(event) => sel.choose(edgeId(e.a, e.b), additiveGesture(event))}
                  >
                    <title>{`R${e.a} ↔ R${e.b} · ${e.lengthMm != null ? `${e.lengthMm} mm` : 'no physical-link row'} · ${e.channelIds.length} channels`}</title>
                  </line>
                );
              })}
              {model.nodes.map((n) => {
                const p = pos(n.id);
                if (!p) return null;
                return (
                  <g key={n.id}>
                    <rect x={p.x - 30} y={p.y - 30} width={60} height={60} rx={4}
                          className="loom-fcell">
                      <title>{`R${n.id} at [${n.col},${n.row}] · ${Object.entries(n.attached).map(([k, v]) => `${v}×${k}`).join(', ') || 'no agents seated'}`}</title>
                    </rect>
                    <text x={p.x} y={p.y - 4} textAnchor="middle" className="cv-label">R{n.id}</text>
                    <text x={p.x} y={p.y + 11} textAnchor="middle" className="cv-label-sm">
                      {n.col},{n.row}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
          <p className="loom-hint">
            Click a link for its channels and length · dashed lines cross the
            array (wraparound or long-haul) · positions are the certified router
            coordinates, not a placed-and-routed die.
          </p>
        </div>
      }
      right={
        <>
          <RailSection
            title="Link inspector"
            note="Channel width, latency and adjacency are compiler output; RC parasitics and slack are not."
          >
            <From origin="DERIVED" artifact="topology" />
            {pair ? (
              <>
                <Kv label="selection id" value={<code>{loomIdText(pair)}</code>} />
                {!edge && (
                  <p className="warn">
                    No adjacency between R{pair.src} and R{pair.dst} in this
                    revision. The id is kept; nothing is drawn in its place.
                  </p>
                )}
                {edge && (
                  <>
                    <Kv label="between" value={<code>R{edge.a} ↔ R{edge.b}</code>} />
                    <Kv label="physical link" value={
                      edge.id != null
                        ? <code>{edge.id}</code>
                        : <span className="status status-muted">NOT CARRIED</span>
                    } />
                    <Kv label="length" value={edge.lengthMm != null ? `${edge.lengthMm} mm` : '—'} mono />
                    <Kv label="channels" value={String(edge.channelIds.length)} mono />
                    <table className="tbl">
                      <thead>
                        <tr><th>channel</th><th className="num">width</th><th className="num">latency</th></tr>
                      </thead>
                      <tbody>
                        {edge.channelIds.map((cid) => {
                          const c = topology.channels.find((x) => x.channel_id === cid);
                          return (
                            <tr key={cid}>
                              <td><code>{cid}</code></td>
                              <td className="num">{c ? `${c.width_bits}b` : '—'}</td>
                              <td className="num">{c ? `${c.latency_cycles} cyc` : '—'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </>
                )}
              </>
            ) : (
              <p className="muted">Select a link on the placement.</p>
            )}
            <ExtensionPoint
              title="Parasitics, slack and retiming"
              needs="an SDA/STA report; Studio cannot insert pipeline stages it has no timing evidence for"
            />
          </RailSection>

          {problems}
        </>
      }
    />
  );
}
