import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import type { LoweringOperation } from '../../api';
import { parallelismOf, type LoomData } from './data';
import { ExtensionPoint, Kv, Panes, RailSection, From, SummaryStrip } from './parts';

type Perspective = 'flow' | 'qos' | 'gantt';

const PERSPECTIVES: { id: Perspective; label: string }[] = [
  { id: 'flow', label: '1. Phase flow & active links' },
  { id: 'qos', label: '2. Collectives & QoS table' },
  { id: 'gantt', label: '3. Execution timeline' },
];

function bytes(v: number): string {
  if (v >= 1 << 30) return `${(v / (1 << 30)).toFixed(1)} GiB`;
  if (v >= 1 << 20) return `${(v / (1 << 20)).toFixed(1)} MiB`;
  if (v >= 1 << 10) return `${(v / (1 << 10)).toFixed(1)} KiB`;
  return `${v} B`;
}

export default function WorkloadLoom({ data, problems }: {
  data: LoomData;
  problems?: ReactNode;
}): ReactElement {
  const [perspective, setPerspective] = useState<Perspective>('flow');
  const workload = data.design?.workload ?? null;
  const requirements = data.design?.requirements ?? [];
  const lowering = data.lowering.result.state === 'ready'
    ? data.lowering.result.data
    : null;

  const phases = useMemo(() => {
    const buckets = new Map<string, LoweringOperation[]>();
    for (const op of lowering?.operations ?? []) {
      const key = op.phase ?? 'unphased';
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)?.push(op);
    }
    return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [lowering]);

  const topFlows = useMemo(
    () => (lowering?.flows ?? [])
      .slice()
      .sort((a, b) => b.payload_bytes - a.payload_bytes)
      .slice(0, 12),
    [lowering],
  );

  const p = parallelismOf(data);

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Model input"
            note="Authored on the draft. Editing happens on Design — this workspace never rewrites the workload."
          >
            <From origin="AUTHORED" artifact="draft" />
            <Kv label="model family" value={<code>{workload?.model_family ?? '—'}</code>} />
            <Kv label="model" value={workload?.model_name ?? '—'} />
            <Kv label="serving mode" value={workload?.serving_mode ?? '—'} />
            <Kv label="content digest" value={<code>{workload?.workload_source_ref?.content_digest
              ? `${workload.workload_source_ref.content_digest.slice(0, 16)}…`
              : '—'}</code>} />
          </RailSection>

          <RailSection title="Parallelism strategy">
            <From
              origin="DERIVED"
              artifact="compile_result"
              note="the revision's mapping when compiled; draft intent otherwise"
            />
            {data.compileResult.result.state === 'error' && (
              <p className="bad" role="alert">
                Compiled mapping unreadable: {data.compileResult.result.error.message}. Strategy below is draft intent, not the revision's mapping.
              </p>
            )}
            <Kv label="tensor parallel (TP)" value={p?.tp ?? '—'} mono />
            <div className="loom-bar"><span style={{ width: `${Math.min(100, ((p?.tp ?? 0) / 16) * 100)}%` }} /></div>
            <Kv label="expert parallel (EP)" value={p?.ep ?? '—'} mono />
            <div className="loom-bar"><span style={{ width: `${Math.min(100, ((p?.ep ?? 0) / 16) * 100)}%` }} /></div>
            <Kv label="pipeline parallel (PP)" value={p?.pp ?? '—'} mono />
            <div className="loom-bar"><span style={{ width: `${Math.min(100, ((p?.pp ?? 0) / 16) * 100)}%` }} /></div>
            <Kv label="data parallel (DP)" value={p?.dp ?? '—'} mono />
            <div className="loom-bar"><span style={{ width: `${Math.min(100, ((p?.dp ?? 0) / 16) * 100)}%` }} /></div>
          </RailSection>

          <RailSection
            title="Product requirements"
            note="Verdicts are not computed here — this page shows the declared ceilings and floors the RequirementReport is graded against."
          >
            <From origin="AUTHORED" artifact="draft" />
            <table className="tbl">
              <thead>
                <tr>
                  <th>qos / traffic</th>
                  <th className="num">latency ceiling</th>
                  <th className="num">bandwidth floor</th>
                </tr>
              </thead>
              <tbody>
                {requirements.map((r, i) => (
                  <tr key={`${r.qos_class ?? 'q'}-${i}`}>
                    <td>
                      <code>{r.qos_class ?? '—'}</code>
                      <div className="muted">{r.traffic_class ?? '—'}</div>
                    </td>
                    <td className="num">
                      {r.latency_ceiling_cycles != null
                        ? `${r.latency_ceiling_cycles} cyc`
                        : '—'}
                    </td>
                    <td className="num">
                      {r.bandwidth_floor_gbps != null
                        ? `${r.bandwidth_floor_gbps} Gbps`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {requirements.length === 0 && (
              <p className="muted">The draft declares no requirements.</p>
            )}
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Traffic class', v: lowering ? <code>{lowering.traffic_class}</code> : '—', tone: 'info' },
            { k: 'Participants', v: lowering ? String(lowering.participant_count) : '—' },
            { k: 'Collectives', v: lowering ? String(lowering.totals.collectives) : '—' },
            { k: 'Messages', v: lowering ? lowering.totals.messages.toLocaleString() : '—' },
            { k: 'Payload', v: lowering ? bytes(lowering.totals.payload_bytes) : '—' },
          ]} />

          <div className="canvas-toolbar">
            <div className="overlay-tabs" role="tablist" aria-label="Workload perspectives">
              {PERSPECTIVES.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  role="tab"
                  aria-selected={perspective === v.id}
                  className={`overlay-tab${perspective === v.id ? ' active' : ''}`}
                  onClick={() => setPerspective(v.id)}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </div>

          {data.lowering.result.state === 'loading' && (
            <p className="muted" role="status">lowering workload…</p>
          )}
          {data.lowering.result.state === 'error' && (
            <p className="bad">{data.lowering.result.error.message}</p>
          )}
          {!lowering && data.lowering.result.state === 'ready' && (
            <ExtensionPoint
              title="No lowering schedule"
              needs={workload
                ? 'a workload-lowering artifact for this workload id'
                : 'a workload bound to the project draft'}
            />
          )}

          {lowering && perspective === 'flow' && (
            <>
              <p className="loom-hint">
                Operations grouped by the phase the lowering recorded. This is
                the engine's own schedule, not an animation of it.
              </p>
              <div className="loom-phases">
                {phases.map(([phase, ops]) => (
                  <div className="loom-phase" key={phase}>
                    <div className="loom-phase-head">
                      <b>{phase}</b>
                      <span>{ops.length} ops</span>
                    </div>
                    <ul>
                      {ops.slice(0, 40).map((op) => (
                        <li key={op.operation_id} title={op.label}>
                          <code>{op.kind}</code>
                          {op.owner != null && <em> · rank {op.owner}</em>}
                        </li>
                      ))}
                      {ops.length > 40 && <li className="muted">…{ops.length - 40} more</li>}
                    </ul>
                  </div>
                ))}
              </div>
            </>
          )}

          {lowering && perspective === 'qos' && (
            <>
              <RailSection title="Collective schedules">
                <From origin="DERIVED" artifact="lowering" />
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>kind</th><th>algorithm</th>
                      <th className="num">k</th><th className="num">steps</th>
                      <th className="num">messages</th><th className="num">payload</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lowering.collectives.map((c, i) => (
                      <tr key={`${c.collective_id}-${i}`}>
                        <td><code>{c.kind}</code></td>
                        <td>{c.algorithm}</td>
                        <td className="num">{c.k}</td>
                        <td className="num">{c.steps}</td>
                        <td className="num">{c.message_count.toLocaleString()}</td>
                        <td className="num">{bytes(c.payload_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {lowering.collectives.length === 0 && (
                  <p className="muted">The lowering recorded no collectives.</p>
                )}
              </RailSection>
            </>
          )}

          {lowering && perspective === 'gantt' && (
            <ExtensionPoint
              title="Execution timeline"
              needs="a per-cycle schedule artifact; the lowering carries dependencies and steps, not start times"
            />
          )}
        </div>
      }
      right={
        <>
          <RailSection
            title="Flow inspector"
            note="Ranks are the lowering's participants — this workspace does not claim a mapping from rank to tile."
          >
            <From origin="DERIVED" artifact="lowering" />
            {lowering ? (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>flow</th><th>class</th>
                    <th className="num">msgs</th><th className="num">bytes</th>
                  </tr>
                </thead>
                <tbody>
                  {topFlows.map((f, i) => (
                    <tr key={`${f.operation_id}-${i}`}>
                      <td><code>{f.src_rank} → {f.dst_rank}</code></td>
                      <td>{f.traffic_class}</td>
                      <td className="num">{f.message_count.toLocaleString()}</td>
                      <td className="num">{bytes(f.payload_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No lowering loaded.</p>
            )}
          </RailSection>

          <RailSection title="Memory demand">
            <From origin="DERIVED" artifact="lowering" />
            {lowering ? (
              <>
                <Kv label="operations" value={String(lowering.memory_demand.operation_count)} mono />
                <Kv label="compute ops" value={String(lowering.memory_demand.compute_count)} mono />
                <Kv label="memory-bound ops" value={String(lowering.memory_demand.memory_demand_ops)} mono />
                <Kv label="operand bytes" value={bytes(lowering.memory_demand.total_operand_bytes)} mono />
                <Kv label="carries demand" value={lowering.memory_demand.has_memory_demand ? 'yes' : 'no'} />
              </>
            ) : (
              <p className="muted">No lowering loaded.</p>
            )}
          </RailSection>

          <RailSection title="Next step">
            <p className="muted">
              A profile becomes evidence only when a run executes it. The
              evaluation page owns that action — no run is fired from here.
            </p>
            <Link className="btn" to={`/projects/${data.projectId}/evaluate`}>
              Open evaluation
            </Link>
          </RailSection>

          {problems}
        </>
      }
    />
  );
}
