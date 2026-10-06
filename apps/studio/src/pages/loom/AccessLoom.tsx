import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { api, type CanonicalRoute } from '../../api';
import { useAsync } from '../../studio';
import { busiestPairs, loomPlan, type LoomData } from './data';
import { pairId, pickId } from './selection';
import type { LoomSelectionStore } from './selectionStore';
import { ExtensionPoint, Kv, Panes, RailSection, SummaryStrip } from './parts';

export default function AccessLoom({ data, sel, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  problems?: ReactNode;
}): ReactElement {
  const plan = useMemo(() => loomPlan(data), [data]);
  const traffic = data.traffic.result.state === 'ready'
    ? data.traffic.result.data
    : null;

  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const [asked, setAsked] = useState(false);

  // The counts are read back off the matrix by the selected pair, never held
  // in the selection: a measured cell is an artifact row, so the artifact stays
  // the only thing it is read from.
  const heldPair = pickId(sel.selection, 'pair');
  const cell = heldPair && traffic
    ? {
      src: heldPair.src,
      dst: heldPair.dst,
      packets: traffic.matrix[heldPair.src]?.[heldPair.dst] ?? 0,
      flits: traffic.flit_matrix[heldPair.src]?.[heldPair.dst] ?? 0,
    }
    : null;

  const route = useAsync<CanonicalRoute | null>(() => {
    if (!asked || !data.revisionId || !plan.routingClass) return Promise.resolve(null);
    return api.route(data.revisionId, {
      routingClass: plan.routingClass,
      src: src === '' ? null : Number(src),
      dst: dst === '' ? null : Number(dst),
    });
  }, [asked, data.revisionId, plan.routingClass, src, dst]);
  const path = route.result.state === 'ready' ? route.result.data : null;

  const max = useMemo(
    () => Math.max(1, ...(traffic ? traffic.matrix.flat() : [1])),
    [traffic],
  );
  const shade = (v: number): string =>
    v <= 0 ? 'transparent'
      : `color-mix(in srgb, var(--info) ${Math.round(14 + 86 * Math.min(1, v / max))}%, transparent)`;

  const CELL = 26;
  const PAD = 34;
  const nodes = traffic?.nodes ?? 0;
  const W = PAD + nodes * CELL + 8;
  const H = PAD + nodes * CELL + 22;
  const pairs = busiestPairs(traffic, 5);

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Matrix source"
            note="Two independent artifacts: the executed trace counts traffic per node pair; the certified route table answers where a path goes. Studio never treats one as the other."
          >
            <Kv label="trace" value={traffic ? <code>{traffic.source.trace}</code> : '—'} />
            <Kv label="backend" value={traffic ? <code>{traffic.source.backend}</code> : '—'} />
            <Kv label="declared packets" value={traffic?.source.declared_packets ?? '—'} mono />
            <Kv label="routing class" value={<code>{plan.routingClass ?? '—'}</code>} />
            <Kv label="initiator routers" value={String(plan.initiatorRouters.length)} mono />
            <Kv label="target routers" value={String(plan.targetRouters.length)} mono />
            <p className="loom-note">
              Roles derive from the endpoint kinds attached to each router in
              the certified topology — they are not an authored field.
            </p>
          </RailSection>

          <RailSection title="Path query">
            <label className="loom-field">
              <span>source router (initiator)</span>
              <select value={src} onChange={(e) => setSrc(e.target.value)}>
                <option value="">first</option>
                {plan.routers.map((r) => (
                  <option key={r.router_id} value={String(r.router_id)}>
                    R{r.router_id}{plan.initiatorRouters.includes(r.router_id) ? ' · initiator' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="loom-field">
              <span>destination router (target)</span>
              <select value={dst} onChange={(e) => setDst(e.target.value)}>
                <option value="">last</option>
                {plan.routers.map((r) => (
                  <option key={r.router_id} value={String(r.router_id)}>
                    R{r.router_id}{plan.targetRouters.includes(r.router_id) ? ' · target' : ''}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn"
              disabled={!data.revisionId || !plan.routingClass}
              onClick={() => setAsked(true)}
            >
              Show path
            </button>
            {!plan.routingClass && (
              <p className="muted">
                Routing classes come from the compile groups; none loaded on
                this revision.
              </p>
            )}
          </RailSection>

          <RailSection title="Permission column">
            <ExtensionPoint
              title="RW / RO / BLK access verdicts"
              needs="an address-map and access-policy artifact from the compiler; the frozen views carry no per-pair permission"
            />
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Nodes', v: traffic ? String(traffic.nodes) : '—', tone: 'info' },
            { k: 'Packets', v: traffic ? traffic.packets.toLocaleString() : '—' },
            { k: 'Flits', v: traffic ? traffic.flits.toLocaleString() : '—' },
            { k: 'Distinct pairs', v: traffic ? `${traffic.distinct_pairs}` : '—' },
            { k: 'Cells shown', v: traffic ? 'measured, not permitted' : '—' },
          ]} />

          {data.traffic.result.state === 'loading' && (
            <p className="muted" role="status">counting packets…</p>
          )}

          {data.traffic.result.state === 'error' && (
            <p className="bad" role="alert">
              Measured matrix unreadable: {data.traffic.result.error.message}. This is a read failure, not an empty trace.
            </p>
          )}

          {!traffic && data.traffic.result.state === 'ready' && (
            <ExtensionPoint
              title="No measured matrix on this project"
              needs="an evaluated run: the matrix is counted from the trace a run actually executed, so it exists only after evaluation"
            />
          )}

          {traffic && (
            <>
              <div className="loom-table-wrap">
                <svg
                  viewBox={`0 0 ${W} ${H}`}
                  className="canvas loom-matrix"
                  role="img"
                  aria-label={`Measured traffic matrix, ${nodes} sources by ${nodes} destinations`}
                >
                  {traffic.matrix.map((row, s) => row.map((v, d) => {
                    const key = `${s}-${d}`;
                    const on = cell?.src === s && cell?.dst === d;
                    return (
                      <g key={key}>
                        <rect
                          x={PAD + d * CELL}
                          y={PAD + s * CELL}
                          width={CELL - 1}
                          height={CELL - 1}
                          fill={s === d ? 'var(--border)' : shade(v)}
                          stroke={on ? 'var(--accent)' : 'var(--border)'}
                          strokeWidth={on ? 2 : 0.5}
                          className={s === d ? undefined : 'loom-cell'}
                          onClick={s === d || v <= 0
                            ? undefined
                            : () => sel.select(pairId(s, d))}
                        >
                          <title>{`${s} → ${d}: ${v.toLocaleString()} packets`}</title>
                        </rect>
                      </g>
                    );
                  }))}
                  {Array.from({ length: nodes }, (_, i) => (
                    <text key={`d${i}`} x={PAD + i * CELL + CELL / 2} y={PAD - 10}
                          textAnchor="middle" className="cv-label-sm">n{i}</text>
                  ))}
                  {Array.from({ length: nodes }, (_, i) => (
                    <text key={`s${i}`} x={PAD - 6} y={PAD + i * CELL + CELL / 2 + 3}
                          textAnchor="end" className="cv-label-sm">{i}</text>
                  ))}
                </svg>
              </div>
              <p className="loom-hint">
                Cell fill ∝ measured packets on the executed trace · diagonal is
                self-traffic · row = source node, column = destination node.
                Colour says nothing about permission.
              </p>

              <RailSection title="Busiest measured pairs">
                <table className="tbl">
                  <thead>
                    <tr><th>node → node</th><th className="num">packets</th><th className="num">flits</th></tr>
                  </thead>
                  <tbody>
                    {pairs.map((p) => (
                      <tr
                        key={`${p.src}-${p.dst}`}
                        className={cell?.src === p.src && cell?.dst === p.dst ? 'sel' : undefined}
                        onClick={() => sel.select(pairId(p.src, p.dst))}
                      >
                        <td><code>{p.src} → {p.dst}</code></td>
                        <td className="num">{p.packets.toLocaleString()}</td>
                        <td className="num">{p.flits.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </RailSection>
            </>
          )}
        </div>
      }
      right={
        <>
          <RailSection
            title="Path inspector"
            note="Walked server-side from the table frozen at certification. This view never runs pathfinding, and a derived path is not a measurement."
          >
            {path ? (
              <>
                <Kv label="class" value={<code>{path.routing_class}</code>} />
                <Kv label="path" value={<code>r{path.src} → r{path.dst}</code>} />
                <Kv label="routers" value={String(path.routers.length)} mono />
                <Kv label="hops" value={String(path.hops.length)} mono />
                <Kv label="terminates" value={path.terminates ? 'yes' : 'no'} />
                {path.terminal && <Kv label="terminal" value={<code>{path.terminal}</code>} />}
                {path.reason && <Kv label="reason" value={path.reason} />}
                <table className="tbl">
                  <thead>
                    <tr><th>#</th><th>hop</th><th>ports</th></tr>
                  </thead>
                  <tbody>
                    {path.hops.map((h, i) => (
                      <tr key={`${h.channel_id}-${i}`}>
                        <td className="num">{i + 1}</td>
                        <td><code>R{h.src_router} → R{h.dst_router}</code></td>
                        <td className="num">{h.src_port} → {h.dst_port}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <p className="muted">
                Pick a source and destination, then show the path. Nothing is
                inferred from the traffic matrix.
              </p>
            )}
            {route.result.state === 'error' && (
              <p className="bad">{route.result.error.message}</p>
            )}
          </RailSection>

          <RailSection title="Measured cell">
            {cell ? (
              <>
                <Kv label="pair" value={<code>{cell.src} → {cell.dst}</code>} />
                <Kv label="packets" value={cell.packets.toLocaleString()} mono />
                <Kv label="flits" value={cell.flits.toLocaleString()} mono />
                <Kv label="permission" value={<span className="status status-muted">NO ARTIFACT</span>} />
              </>
            ) : (
              <p className="muted">Select a cell to read its measured counts.</p>
            )}
          </RailSection>

          {problems}
        </>
      }
    />
  );
}
