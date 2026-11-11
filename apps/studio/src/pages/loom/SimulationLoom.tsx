import {
  useEffect, useMemo, useState, type ReactElement, type ReactNode,
} from 'react';
import { Link } from '../../studio';
import { api, type CompareView } from '../../api';
import { useAsync } from '../../studio';
import { fmtNum, Hash, humanize, StatusBadge } from '../../components/badges';
import {
  busiestPairs, expectedChannelLoad, loomPlan, resolveRouterPairs,
  ROUTE_SWEEP_LIMIT, sweepPairs, sweepRoutes, type LoomData, type RouteSweep,
} from './data';
import { revisionFreshness, type SectionFreshness } from './freshness';
import { channelId, pairId, pickId } from './selection';
import RunHistoryPanel from './RunHistoryPanel';
import { compareRecordedRunInputs } from './compareInputs';
import RunArtifactVerify from './RunArtifactVerify';
import type { LoomSelectionStore } from './selectionStore';
import {
  ExtensionPoint, FreshWord, Kv, OriginWord, Panes, RailSection, From, SummaryStrip,
} from './parts';
import { SampledLinkSeries } from './TopologyPlanes';

const IDLE_SWEEP: RouteSweep = {
  routes: new Map(), requested: 0, resolved: 0, failed: 0,
  unterminated: 0, unresolvable: 0, routerQueries: 0,
  limit: ROUTE_SWEEP_LIMIT, state: 'idle', error: null,
};

export default function SimulationLoom({ data, sel, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  problems?: ReactNode;
}): ReactElement {
  const run = data.run.result.state === 'ready' ? data.run.result.data : null;
  const trafficUnavailable = data.trafficUnavailable;
  const traffic = data.traffic.result.state === 'ready'
    ? data.traffic.result.data : null;
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const pairs = useMemo(() => busiestPairs(traffic, 5), [traffic]);
  const evaluation = run?.evaluation ?? null;
  const metrics = Object.entries(evaluation?.metrics ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const verdicts = run?.requirements?.entries ?? [];
  const window_ = evaluation?.network_traffic_window ?? null;
  /** The run summary carries the value when the gateway recorded it; the
   *  evaluation metrics carry it otherwise. Both are engine output. */
  const completion = run?.completion_cycles
    ?? evaluation?.metrics?.completion_cycles
    ?? null;

  const [sweep, setSweep] = useState<RouteSweep>(IDLE_SWEEP);
  const plan = useMemo(() => loomPlan(data), [data]);

  /** A sweep in flight must not be left to write into an unmounted view, and
   *  a new revision or run invalidates the previous walk entirely. */
  const sweepKey = `${data.revisionId}|${traffic?.run_id}|${plan.routingClass}`;
  useEffect(() => { setSweep(IDLE_SWEEP); }, [sweepKey]);

  const load = useMemo(
    () => expectedChannelLoad(traffic, sweep.routes, topology),
    [traffic, sweep.routes, topology],
  );

  const tracedPairs = useMemo(() => sweepPairs(traffic), [traffic]);
  // Endpoint pairs become router pairs through the certified attachment
  // only. Pairs with no certified seat are counted, never queried as
  // though an endpoint id were a router id.
  const resolvedPairs = useMemo(
    () => resolveRouterPairs(tracedPairs, topology),
    [tracedPairs, topology],
  );
  const canSweep = Boolean(
    data.revisionId && plan.routingClass && resolvedPairs.routable.length,
  );

  const startSweep = async (): Promise<void> => {
    if (!data.revisionId || !plan.routingClass) return;
    setSweep({
      ...IDLE_SWEEP,
      requested: tracedPairs.length,
      unresolvable: resolvedPairs.unresolvable.length,
      state: 'loading',
    });
    try {
      const result = await sweepRoutes(
        data.revisionId, plan.routingClass, resolvedPairs.routable,
      );
      setSweep((current) => ({
        ...current, state: 'ready', ...result,
        unresolvable: resolvedPairs.unresolvable.length,
      }));
    } catch (e) {
      setSweep((current) => ({
        ...current,
        state: 'error',
        error: e instanceof Error ? e.message : String(e),
      }));
    }
  };

  const heldChannel = pickId(sel.selection, 'channel');
  const heldPair = pickId(sel.selection, 'pair');
  const loadSelected = heldChannel?.channelId ?? null;
  const picked = loadSelected != null
    ? load.find((l) => l.channelId === loadSelected) ?? null
    : null;
  const share = (flits: number): string => (
    traffic && traffic.flits > 0
      ? `${((flits / traffic.flits) * 100).toFixed(1)}%`
      : '—'
  );

  const stage = ((): ReactElement => {
    if (data.run.result.state === 'loading') {
      return <p className="muted" role="status">loading run…</p>;
    }
    if (data.run.result.state === 'error') {
      return <p className="bad">{data.run.result.error.message}</p>;
    }
    if (!run) {
      return (
        <ExtensionPoint
          title="No run on this project"
          needs="an evaluated run. Simulation numbers are execution evidence — they exist only after a backend produced them"
        >
          <Link className="btn" to={`/projects/${data.projectId}/evaluate`}>
            Open evaluation
          </Link>
        </ExtensionPoint>
      );
    }
    return (
      <>
        <div className={`verdict-banner ${run.status === 'EVALUATED' ? 'verdict-evaluated' : 'verdict-not_run'}`}>
          <span className="verdict-text">
            <strong>{run.status ?? 'UNKNOWN'}</strong>
            {run.backend ? <> · backend <code>{run.backend}</code></> : null}
            {run.qualification ? <> · qualification <code>{run.qualification}</code></> : null}
            {run.reason ? <> · {run.reason}</> : null}
            {!run.reason && run.status !== 'EVALUATED' && (
              <> · no metrics are shown for this outcome</>
            )}
          </span>
        </div>

        <div className="loom-metrics">
          <RailSection
            title="Present metrics"
            note="Only keys the backend actually emitted appear. An absent metric is omitted, never zero-filled."
          >
            <From
              origin="MEASURED"
              artifact="run"
              data={data}
            />
            {metrics.length ? (
              <div className="kv-grid">
                {metrics.map(([k, v]) => (
                  <div className="kv" key={k}>
                    <span><code>{humanize(k)}</code></span>
                    <span className="num">{fmtNum(v)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                {evaluation
                  ? 'The evaluation view carries no metrics for this status.'
                  : 'This run has no evaluation view attached.'}
              </p>
            )}
            {evaluation?.fidelity_warning && (
              <p className="warn">{evaluation.fidelity_warning}</p>
            )}
          </RailSection>

          <RailSection title="Execution window">
            <From
              origin="MEASURED"
              artifact="run"
              data={data}
            />
            <Kv label="window cycles" value={window_ ? window_.window_cycles.toLocaleString() : '—'} mono />
            <Kv label="wall time" value={window_?.wall_time_ns != null ? `${window_.wall_time_ns.toLocaleString()} ns` : '—'} mono />
            <Kv label="cycles only" value={window_ ? (window_.cycles_only ? 'yes' : 'no') : '—'} />
            <Kv label="evidence" value={<Hash value={run.evidence?.raw_evidence_digest ?? null} />} />
          </RailSection>

          <RailSection
            title="Requirement verdicts"
            note="Verdicts come from the engine's RequirementReport; this view adds no verdict of its own."
          >
            <From
              origin="MEASURED"
              artifact="run"
              data={data}
            />
            {verdicts.length ? (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>class</th><th>verdict</th>
                    <th className="num">required</th><th className="num">measured</th>
                    <th>authority</th>
                  </tr>
                </thead>
                <tbody>
                  {verdicts.map((e, i) => (
                    <tr key={`${e.requirement_index}-${i}`}>
                      <td>{e.qos_class ?? e.traffic_class ?? '—'}</td>
                      <td><StatusBadge status={e.verdict} /></td>
                      <td className="num">{e.required ?? '—'}</td>
                      <td className="num">{e.measured ?? '—'}</td>
                      <td><code>{e.metric_authority}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No requirement report attached to this run.</p>
            )}
          </RailSection>

          <RailSection
            title="Expected per-channel load"
            note="Derived attribution via frozen routes — not measured per-link counters. Walk the traced pairs to attribute load."
          >
            {traffic && <From
              origin="DERIVED"
              artifact="traffic_matrix"
              data={data}
            />}
            <div className="loom-actions">
              <button
                type="button"
                className="btn"
                disabled={!canSweep || sweep.state === 'loading'}
                onClick={() => { void startSweep(); }}
              >
                {sweep.state === 'loading' ? 'Walking routes…' : 'Walk traced pairs'}
              </button>
              {sweep.state !== 'idle' && (
                <span className="muted">
                  {sweep.resolved}/{sweep.requested} resolved
                  {sweep.failed > 0 && `, ${sweep.failed} failed`}
                  {sweep.unterminated > 0 && `, ${sweep.unterminated} unterminated`}
                  {sweep.unresolvable > 0 && `, ${sweep.unresolvable} unseated`}
                  {sweep.routerQueries > 0 && ` (${sweep.routerQueries} router queries)`}
                </span>
              )}
            </div>

            {data.traffic.result.state === 'error' ? (
              <p className="bad" role="alert">
                Measured matrix unreadable: {data.traffic.result.error.message}. No pair is walked on a failed read.
              </p>
            ) : trafficUnavailable ? (
              <p className="muted" role="status">Measured matrix unavailable: {trafficUnavailable.reason} No pair is walked.</p>
            ) : !tracedPairs.length ? (
              <ExtensionPoint
                title="No traced pair to walk"
                needs={traffic
                  ? 'a trace with traffic between distinct nodes; the matrix only ever carries src→dst the run emitted'
                  : 'an evaluated run. There is no traffic to attribute before a trace exists.'}
              />
            ) : (
              <>
                {tracedPairs.length >= ROUTE_SWEEP_LIMIT && (
                  <p className="warn">
                    The trace carries more than {ROUTE_SWEEP_LIMIT} pairs, so
                    the walk covers the busiest {ROUTE_SWEEP_LIMIT} only.
                    Load below is a partial account of the trace.
                  </p>
                )}
                {sweep.state === 'error' && <p className="bad">{sweep.error}</p>}
                {sweep.state === 'ready' && load.length > 0 && (
                  <>
                    <table className="tbl loom-table">
                      <thead>
                        <tr>
                          <th className="num">ch</th>
                          <th>routers</th>
                          <th className="num">flits</th>
                          <th className="num">share</th>
                          <th className="num">pairs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {load.slice(0, 20).map((l) => (
                          <tr
                            key={l.channelId}
                            className={loadSelected === l.channelId ? 'sel' : undefined}
                            onClick={() => sel.select(channelId(l.channelId))}
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                sel.select(channelId(l.channelId));
                              }
                            }}
                          >
                            <td className="num"><code>{l.channelId}</code></td>
                            <td><code>R{l.srcRouter} → R{l.dstRouter}</code></td>
                            <td className="num">{l.flits.toLocaleString()}</td>
                            <td className="num">{share(l.flits)}</td>
                            <td className="num">{l.pairs}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="loom-note">
                      Busiest first, top 20 of {load.length} loaded channels.
                      Share is against total measured flits, so the same flit
                      appears once per channel it crosses — the column sums
                      above 100% by construction.
                    </p>
                  </>
                )}
                {sweep.state === 'ready' && load.length === 0 && (
                  <p className="muted">
                    {sweep.resolved} route(s) resolved but none crosses a
                    channel, so no channel carries attributed load.
                  </p>
                )}
              </>
            )}
          </RailSection>
        </div>
      </>
    );
  })();

  return (
    <Panes
      left={
        <>
          <RailSection title="Trace source">
            <From
              origin="MEASURED"
              artifact="run"
              data={data}
            />
            <Kv label="run" value={<code>{data.latestRun?.run_id ?? '—'}</code>} />
            <Kv label="completed" value={<code>{data.latestRun?.completed_at ?? '—'}</code>} />
          </RailSection>

          <RailSection title="Run artifact integrity">
            <RunArtifactVerify key={data.latestRun?.run_id ?? 'none'} runId={data.latestRun?.run_id ?? null} />
          </RailSection>

          <RailSection
            title="Unavailable readouts"
            note="Sampled link counters appear in the Simulation stage when this run carries that artifact; the gateway does not expose a cycle-level event trace."
          >
            <ul className="loom-needs">
              <li><b>Cycle scrubber</b> — needs a per-cycle packet trace artifact</li>
              <li><b>Packet-accurate animation</b> — needs timestamped packet events from this run</li>
            </ul>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Run', v: data.latestRun ? <code>{data.latestRun.run_id.slice(0, 12)}</code> : 'none', tone: data.latestRun ? 'info' : 'warn' },
            { k: 'Status', v: data.latestRun?.status ?? 'NOT RUN', tone: data.latestRun?.status === 'EVALUATED' ? 'ok' : undefined },
            { k: 'Completion', v: completion != null ? `${completion.toLocaleString()} cyc` : '—' },
            { k: 'Requirements', v: verdicts.length
              ? `${verdicts.filter((v) => v.verdict === 'SATISFIED').length}/${verdicts.length} SATISFIED`
              : '—',
              tone: verdicts.length && verdicts.every((v) => v.verdict === 'SATISFIED') ? 'ok' : undefined },
            { k: 'Measured pairs', v: traffic ? String(traffic.distinct_pairs) : trafficUnavailable ? 'N/A' : '—' },
          ]} />
          {stage}
          {run && <SampledLinkSeries data={data} runId={run.run_id} />}
          <RunComparison data={data} currentRunId={data.latestRun?.run_id ?? null} currentDesignHash={data.designHash} />
        </div>
      }
      right={
        <>
          <RailSection
            title="Busiest measured pairs"
            note="Counts from the executed trace's endpoint-pair matrix. Link counters are a separate sampled artifact shown in the Simulation stage when this run carries it."
          >
            {traffic && <From
              origin="MEASURED"
              artifact="traffic_matrix"
              data={data}
            />}
            <Kv label="matrix trace" value={traffic ? <code>{traffic.source.trace}</code> : trafficUnavailable ? 'not produced' : '—'} />
            <Kv label="declared packets" value={traffic?.source.declared_packets ?? '—'} mono />
            {pairs.length ? (
              <table className="tbl">
                <thead>
                  <tr><th>node → node</th><th className="num">flits</th></tr>
                </thead>
                <tbody>
                    {pairs.map((p) => (
                      <tr
                        key={`${p.src}-${p.dst}`}
                        className={heldPair?.src === p.src && heldPair?.dst === p.dst ? 'sel' : undefined}
                        onClick={() => sel.select(pairId(p.src, p.dst))}
                      >
                        <td><code>{p.src} → {p.dst}</code></td>
                        <td className="num">{p.flits.toLocaleString()}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            ) : data.traffic.result.state === 'error' ? (
              <p className="bad" role="alert">Measured pairs unreadable: {data.traffic.result.error.message}.</p>
            ) : trafficUnavailable ? (
              <p className="muted" role="status">Measured pairs unavailable: {trafficUnavailable.reason}</p>
            ) : (
              <p className="muted">No traffic matrix attached to this run.</p>
            )}
          </RailSection>

          {picked && (
            <RailSection
              title="Channel inspector"
              note="Channel geometry is certified; the load on it is the derived attribution described above."
            >
              <From
                origin="DERIVED"
                artifact="topology"
                note="geometry; load rows are the derived attribution"
                data={data}
              />
              <Kv label="channel" value={<code>{picked.channelId}</code>} />
              <Kv label="routers" value={<code>R{picked.srcRouter} → R{picked.dstRouter}</code>} />
              <Kv label="width" value={`${picked.widthBits} bits`} mono />
              <Kv label="link latency" value={`${picked.latencyCycles} cyc`} mono />
              <Kv label="attributed flits" value={picked.flits.toLocaleString()} mono />
              <Kv label="share of trace flits" value={share(picked.flits)} mono />
              <Kv label="traced pairs crossing" value={String(picked.pairs)} mono />
              <Kv label="busiest channel" value={picked.channelId === peakChannel(load)
                ? 'yes' : 'no'} />
              <p className="loom-note">
                A pair crosses this channel because the frozen route table says
                so. If the run's real router diverged from that table, the
                attribution is wrong — and no view here carries the observation
                that would prove it.
              </p>
            </RailSection>
          )}

          {/* Per-link breakdown lives once, in the stage sampled-counters
              table: selecting a channel row reads its wait/Tx split. A second
              auto-picked breakdown here duplicated the panel and the fetch. */}
          {problems}
        </>
      }
    />
  );
}

function peakChannel(load: { channelId: number; flits: number }[]): number | null {
  return load.length ? load[0].channelId : null;
}

/** One compared side's freshness against the active revision. The same
 *  CURRENT / FOREIGN_REVISION vocabulary the From badge uses, because it is
 *  the same question — asked twice, once per side, since one badge cannot
 *  answer for two runs. */
function SideFreshness({ side, revisionId, activeRevisionId }: {
  side: string;
  revisionId: string;
  activeRevisionId: string | null;
}): ReactElement {
  const fresh: SectionFreshness | null = revisionFreshness(
    revisionId, activeRevisionId, `run ${side}`);
  if (!fresh) return <></>;
  return (
    <p className="loom-from">
      <OriginWord origin="MEASURED" />
      {' · '}
      <code>run {side}</code>
      {' · '}
      <FreshWord fresh={fresh} />
    </p>
  );
}

/** Two runs, side by side.
 *
 *  The engine decides which rows are comparable and says why the rest are not;
 *  this panel never ranks a row the engine marked inadmissible, and it never
 *  picks a winner. */
function RunComparison({ data, currentRunId, currentDesignHash }: {
  data: LoomData;
  currentRunId: string | null;
  currentDesignHash: string | null;
}): ReactElement {
  const projectId = data.projectId;
  const runs = useAsync(
    () => api.runs({ projectId }),
    [projectId],
  );
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const options = runs.result.state === 'ready' ? runs.result.data.runs : [];
  const evaluated = options.filter((r) => r.status === 'EVALUATED');

  // Default to two runs on the same revision: a cross-workload pair compares
  // nothing, and the engine will say so on every row.
  const defaults = useMemo(() => {
    const sameRevision = currentRunId
      ? evaluated.filter((r) => (
        r.revision_id === evaluated.find((x) => x.run_id === currentRunId)?.revision_id
      ))
      : [];
    const pool = sameRevision.length >= 2 ? sameRevision : evaluated;
    return [pool[0]?.run_id ?? '', pool[1]?.run_id ?? ''] as const;
  }, [evaluated, currentRunId]);

  const selA = a || defaults[0];
  const selB = b || defaults[1];

  const cmp = useAsync<CompareView | null>(
    () => (selA && selB ? api.compare(selA, selB) : Promise.resolve(null)),
    [selA, selB],
  );

  const picker = (
    label: string,
    value: string,
    set: (v: string) => void,
  ): ReactElement => (
    <label className="loom-field">
      <span>{label}</span>
      <select value={value} onChange={(e) => set(e.target.value)}>
        {evaluated.length === 0 && <option value="">no evaluated run</option>}
        {evaluated.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.display_name ?? r.run_id.slice(0, 12)} · {r.run_id.slice(0, 8)} · {r.completion_cycles ?? '—'} cyc
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <RailSection
      title="Run comparison"
      note="Both runs are read from the gateway; comparability and every verdict are the engine's."
    >
      {/* Two runs, two revisions: one section badge cannot answer freshness,
          so there is none here and each compared side is badged on its own
          below instead. */}
      <From
        origin="MEASURED"
        artifact="run"
        note="two runs below, each badged against the active revision"
        data={null}
      />
      {picker('run a', selA, setA)}
      {picker('run b', selB, setB)}

      {runs.result.state === 'loading' && (
        <p className="muted" role="status">loading runs…</p>
      )}
      {runs.result.state === 'error' && <p className="bad">Run history unavailable: {runs.result.error.message}</p>}
      {runs.result.state === 'ready' && (
        <RunHistoryPanel runs={options} currentDesignHash={currentDesignHash} />
      )}

      {cmp.result.state === 'loading' && (
        <p className="muted" role="status">comparing…</p>
      )}
      {cmp.result.state === 'error' && (
        <p className="bad">{cmp.result.error.message}</p>
      )}

      {cmp.result.state === 'ready' && cmp.result.data && (
        <>
          <SideFreshness
            side="a"
            revisionId={cmp.result.data.a.revision_id}
            activeRevisionId={data.revisionId}
          />
          <SideFreshness
            side="b"
            revisionId={cmp.result.data.b.revision_id}
            activeRevisionId={data.revisionId}
          />
          <Kv
            label="comparable"
            value={cmp.result.data.compatibility.compatible
              ? <span className="t-ok">yes</span>
              : <span className="t-warn">no</span>}
          />
          {cmp.result.data.compatibility.reasons.map((reason) => (
            <p key={reason} className="warn">{reason}</p>
          ))}
          {(() => {
            const diffs = compareRecordedRunInputs(cmp.result.data.a, cmp.result.data.b);
            if (diffs.length === 0) {
              return <p className="muted">Recorded inputs match (completeness not guaranteed).</p>;
            }
            return (
              <section aria-label="Recorded input differences">
                <h4>Recorded input differences</h4>
                <table className="tbl"><thead><tr><th>input</th><th>run a</th><th>run b</th></tr></thead><tbody>
                  {diffs.map(diff => <tr key={diff.field}><td>{diff.field}</td><td><code>{diff.runA}</code></td><td><code>{diff.runB}</code></td></tr>)}
                </tbody></table>
              </section>
            );
          })()}
          <h4>Output metric comparison</h4>
          {(() => {
            const rows = cmp.result.data?.rows ?? [];
            const top = rows.filter((row) => !row.dimensions);
            const dimensional = rows.filter((row) => row.dimensions);
            const renderRow = (row: (typeof rows)[number], i: number): ReactElement => (
              <tr key={`${row.question}-${row.key}-${row.dimensions ?? ''}-${i}`}>
                <td>
                  <code>{row.key}</code>
                  {row.dimensions && <div className="muted">{row.dimensions}</div>}
                </td>
                <td className="num">{row.a == null ? '—' : fmtNum(row.a)}</td>
                <td className="num">{row.b == null ? '—' : fmtNum(row.b)}</td>
                <td className="num">
                  {row.delta_b_minus_a == null ? '—' : fmtNum(row.delta_b_minus_a)}
                </td>
                <td title={row.reason ?? undefined}>
                  <StatusBadge status={row.verdict ?? 'UNKNOWN'} />
                </td>
              </tr>
            );
            const head = (
              <tr>
                <th>metric</th>
                <th className="num">a</th>
                <th className="num">b</th>
                <th className="num">Δ</th>
                <th>verdict</th>
              </tr>
            );
            return (
              <>
                <table className="tbl">
                  <thead>{head}</thead>
                  <tbody>{top.map(renderRow)}</tbody>
                </table>
                {dimensional.length > 0 && (
                  <details className="subtle">
                    <summary>Per-rank and dimensional rows ({dimensional.length})</summary>
                    <table className="tbl">
                      <thead>{head}</thead>
                      <tbody>{dimensional.map(renderRow)}</tbody>
                    </table>
                  </details>
                )}
              </>
            );
          })()}
          <p className="loom-note">{cmp.result.data.note}</p>
        </>
      )}
    </RailSection>
  );
}
