/** Access-flow panel (tracker M3-27): joins the authored firewall cell, the
 *  routing-policy preview route and the graph into one verdict for a node pair.
 *
 *  Operates on the LOCAL authoring graph, so its node ids are authoring ids —
 *  not certified router ids. The certified path is a separate, server-side
 *  query; this panel never conflates the two.
 */
import { useState, type ReactElement } from 'react';
import { accessFlow, type AccessVerdict } from '../../graph/accessFlow';
import type { GraphStore } from '../../graph/store';

const TONE: Record<AccessVerdict, string> = {
  PERMITTED: 't-ok',
  READ_ONLY: 't-info',
  DENIED: 't-bad',
  NO_ROUTE: 't-warn',
  NO_POLICY: 't-warn',
  SELF: 'muted',
};

export function AccessFlowPanel({ store }: { store: GraphStore }): ReactElement {
  const doc = store.doc;
  const ids = doc.nodes.map((node) => node.id);
  const [src, setSrc] = useState(ids[0] ?? '');
  const [dst, setDst] = useState(ids[1] ?? ids[0] ?? '');

  if (ids.length < 2) {
    return <p className="muted">Author at least two nodes to trace an access flow.</p>;
  }
  const from = ids.includes(src) ? src : ids[0]!;
  const to = ids.includes(dst) && dst !== from ? dst : (ids.find((id) => id !== from) ?? from);
  const flow = accessFlow(doc, from, to);

  return (
    <div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <label>from
          <select aria-label="access flow source" value={from} onChange={(e) => setSrc(e.target.value)}>
            {ids.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <span className="muted">→</span>
        <label>to
          <select aria-label="access flow target" value={to} onChange={(e) => setDst(e.target.value)}>
            {ids.filter((id) => id !== from).map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
      </div>

      <p data-testid="access-flow-verdict" className={TONE[flow.verdict]} style={{ margin: '6px 0 2px' }}>
        <b>{flow.verdict}</b>{' '}
        <span className="muted">
          ({flow.perm === null ? 'no authored rule — firewall default is deny' : `authored ${flow.perm}`})
        </span>
      </p>

      {flow.nodePath ? (
        <p style={{ fontSize: 12, margin: 0 }}>
          path: <code>{flow.nodePath.join(' → ')}</code>{' '}
          <span className="muted">({flow.hops.length} hop{flow.hops.length === 1 ? '' : 's'})</span>
        </p>
      ) : (
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          {flow.verdict === 'DENIED'
            ? 'No authored rule permits this pair, so no path is traced.'
            : flow.error ?? 'No preview path.'}
        </p>
      )}

      <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        Authored intent only. This preview route is not the certified route, and
        no firewall engine executes the rule.
      </p>
    </div>
  );
}
