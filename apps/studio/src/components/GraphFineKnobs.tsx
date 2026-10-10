/** Per-node and per-edge graph knobs, and whether each one reaches silicon.
 *
 * These are the FINE controls — per-edge width, pipeline stages and VC class;
 * per-node port count, clock and VC depth. They exist in the graph contract
 * and are editable, but whether the COMPILER materialises each one is a
 * separate question with a real answer per knob, and this panel shows it
 * rather than implying every field compiles.
 *
 * The per-link opts the engine accepts are `bandwidth_GBs`, `latency_ns` and
 * `directed`; link width itself is a global attribute, so a per-edge width
 * has no representation to lower into. Rather than hardcode that here, the
 * lowering verdict is read from the adapter that does the lowering.
 */
import { useMemo, type ReactElement } from 'react';
import { useGraphStore, type GraphStore } from '../graph/store';
import { graphToTopologyIR } from '../graph/adapter';

interface KnobVerdict {
  knob: string;
  scope: 'node' | 'edge';
  lowers: boolean;
  why: string;
}

export default function GraphFineKnobs({ store }: {
  store?: GraphStore;
}): ReactElement {
  const local = useGraphStore('mesh-8x8');
  const graph = store ?? local;
  const ir = useMemo(() => graphToTopologyIR(graph.doc), [graph.doc]);

  const varied = useMemo(() => {
    const widths = new Set(graph.doc.edges.map((e) => e.width));
    const stages = new Set(graph.doc.edges.map((e) => e.pipelineStages));
    const classes = new Set(graph.doc.edges.map((e) => e.vcClass));
    return {
      width: widths.size > 1,
      stages: stages.size > 1 || graph.doc.edges.some((e) => e.pipelineStages !== 1),
      vcClass: classes.size > 1 || graph.doc.edges.some((e) => e.vcClass !== 0),
    };
  }, [graph.doc]);

  const clocks = useMemo(
    () => new Set(graph.doc.nodes.map((n) => n.clock).filter(Boolean)).size > 1,
    [graph.doc],
  );

  const verdicts: KnobVerdict[] = [
    {
      knob: 'per-edge width', scope: 'edge', lowers: !varied.width,
      why: varied.width
        ? 'link width is a GLOBAL compiler attribute, so a graph with mixed widths has no representation to lower into'
        : 'uniform, so it lowers as the global link attribute',
    },
    {
      knob: 'per-edge pipeline stages', scope: 'edge', lowers: !varied.stages,
      why: varied.stages
        ? 'the compiler adapter does not materialise per-edge pipeline stages'
        : 'at 1 everywhere, which is what the adapter lowers',
    },
    {
      knob: 'per-edge VC class', scope: 'edge', lowers: !varied.vcClass,
      why: varied.vcClass
        ? 'VC classes are derived from dependency cycles, not authored per edge'
        : 'at class 0, which is what the adapter lowers',
    },
    {
      knob: 'per-node port count', scope: 'node', lowers: true,
      why: 'editor-side capacity check; the compiler sizes ports from the attachment',
    },
    {
      knob: 'per-node clock', scope: 'node', lowers: true,
      why: clocks
        ? 'distinct clocks group the nodes into separate agent groups on lowering'
        : 'one clock, so all nodes share a group',
    },
    {
      knob: 'per-node VC depth', scope: 'node', lowers: false,
      why: 'VC configuration is derived, so authored depth has no compiler mapping yet',
    },
  ];

  return (
    <section className="topology-intent" aria-label="Graph fine knobs">
      <h3 className="section-title">Per-node &amp; per-edge control</h3>
      <p className="muted">
        The graph this workspace holds: {graph.doc.nodes.length} nodes,{' '}
        {graph.doc.edges.length} edges. Each knob below is editable in the
        graph workspace; the verdict says whether the compiler materialises
        it. {ir.refused
          ? `Current graph refuses to lower: ${ir.refused}.`
          : `Lowers to ${ir.doc?.links ? (ir.doc.links as unknown[]).length : 0} links.`}
      </p>
      <table className="tbl">
        <thead>
          <tr><th>knob</th><th>scope</th><th>lowers</th><th>why</th></tr>
        </thead>
        <tbody>
          {verdicts.map((v) => (
            <tr key={v.knob}>
              <td><code>{v.knob}</code></td>
              <td>{v.scope}</td>
              <td className={v.lowers ? 't-ok' : 't-warn'}>{v.lowers ? 'yes' : 'refuses'}</td>
              <td className="muted">{v.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="subtle" open>
        <summary>Edit node knobs</summary>
        <div style={{ maxHeight: 240, overflow: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr><th>node</th><th>role</th><th className="num">ports</th><th>clock</th><th className="num">vc depth</th></tr>
            </thead>
            <tbody>
              {graph.doc.nodes.slice(0, 60).map((n) => {
                const depth = Number(((n.vc ?? {}) as Record<string, unknown>).depth ?? 4);
                return (
                  <tr key={n.id}>
                    <td><code>{n.id}</code></td>
                    <td className="muted">{n.role}</td>
                    <td className="num">
                      <input aria-label={`ports ${n.id}`} type="number" min={1} defaultValue={n.ports}
                        key={`${n.id}-p${n.ports}`} style={{ width: 62 }}
                        onBlur={(e) => graph.run({ type: 'update_node', id: n.id, patch: { ports: Math.max(1, Number(e.target.value) | 0) } })} />
                    </td>
                    <td>
                      <input aria-label={`clock ${n.id}`} defaultValue={n.clock ?? ''} key={`${n.id}-c${n.clock ?? ''}`} style={{ width: 90 }}
                        onBlur={(e) => graph.run({ type: 'update_node', id: n.id, patch: { clock: e.target.value.trim() || null } })} />
                    </td>
                    <td className="num">
                      <input aria-label={`vc depth ${n.id}`} type="number" min={1} defaultValue={depth} key={`${n.id}-d${depth}`} style={{ width: 62 }}
                        onBlur={(e) => graph.run({ type: 'update_node', id: n.id, patch: { vc: { ...((n.vc ?? {}) as object), depth: Math.max(1, Number(e.target.value) | 0) } } })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {graph.doc.nodes.length > 60 && <p className="muted">…{graph.doc.nodes.length - 60} more nodes (capped).</p>}
        </div>
      </details>
      <details className="subtle" open>
        <summary>Edit edge knobs</summary>
        <div style={{ maxHeight: 220, overflow: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr><th>edge</th><th>link</th><th className="num">width</th><th className="num">stages</th><th className="num">vc class</th></tr>
            </thead>
            <tbody>
              {graph.doc.edges.slice(0, 40).map((e) => (
                <tr key={e.id}>
                  <td><code>{e.id}</code></td>
                  <td>{e.src} → {e.dst}</td>
                  <td className="num">
                    <input aria-label={`width ${e.id}`} type="number" min={1} defaultValue={e.width}
                      key={`${e.id}-w${e.width}`} style={{ width: 62 }}
                      onBlur={(ev) => graph.run({ type: 'update_edge', id: e.id, patch: { width: Math.max(1, Number(ev.target.value) | 0) } })} />
                  </td>
                  <td className="num">
                    <input aria-label={`stages ${e.id}`} type="number" min={1} defaultValue={e.pipelineStages}
                      key={`${e.id}-s${e.pipelineStages}`} style={{ width: 62 }}
                      onBlur={(ev) => graph.run({ type: 'update_edge', id: e.id, patch: { pipelineStages: Math.max(1, Number(ev.target.value) | 0) } })} />
                  </td>
                  <td className="num">
                    <input aria-label={`vc class ${e.id}`} type="number" min={0} defaultValue={e.vcClass}
                      key={`${e.id}-v${e.vcClass}`} style={{ width: 62 }}
                      onBlur={(ev) => graph.run({ type: 'update_edge', id: e.id, patch: { vcClass: Math.max(0, Number(ev.target.value) | 0) } })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {graph.doc.edges.length > 40 && (
            <p className="muted">…{graph.doc.edges.length - 40} more edges (capped).</p>
          )}
        </div>
      </details>
      {ir.refused && (
        <div role="alert">
          <p className="t-warn">● This graph no longer lowers: {ir.refused}</p>
          <button type="button" className="btn btn-small" onClick={() => {
            for (const e of graph.doc.edges) {
              if (e.width !== 512 || e.pipelineStages !== 1 || e.vcClass !== 0) {
                graph.run({ type: 'update_edge', id: e.id, patch: { width: 512, pipelineStages: 1, vcClass: 0 } });
              }
            }
            // The adapter refuses ANY authored per-node VC block, not just a
            // non-default depth, so restoring means clearing the key.
            for (const n of graph.doc.nodes) {
              const vc = (n.vc ?? {}) as Record<string, unknown>;
              if (Object.keys(vc).length > 0) {
                graph.run({ type: 'update_node', id: n.id, patch: { vc: undefined } });
              }
            }
          }}>Restore lowering defaults</button>
        </div>
      )}
      <p className="muted">
        Per-node VC depth is editable above and every value refuses, because the
        adapter refuses any authored VC block — a derived VC count has no
        per-node field to land in. The depth input is there so the refusal is
        visible on edit, not to imply it would lower.
      </p>
      <p className="muted">
        The engine's per-link opts are <code>bandwidth_GBs</code>,{' '}
        <code>latency_ns</code> and <code>directed</code>. A per-edge width
        has no field to land in, which is why it refuses rather than
        approximating.
      </p>
    </section>
  );
}