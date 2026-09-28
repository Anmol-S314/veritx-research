import { useState, type ReactElement } from 'react';
import { CapabilityDetail } from '../components/CapabilityDetail';
import {
  CAPABILITIES,
  CORE_SYSTEMS,
  HISTORY_ROWS,
  MATURITIES,
  MATURITY_BLURB,
  maturityCounts,
  type Maturity,
} from '../components/ImplementationLab/capabilityLedger';

type Filter = Maturity | 'ALL';

/**
 * §32 Capability Explorer — every archaeology record appears here, plus
 * the core product systems that are not archaeology rows. Nothing is
 * hidden because it has not reached PRODUCT; the maturity badge says
 * what the user can do with each feature.
 */
export function CapabilitiesPage(): ReactElement {
  const [filter, setFilter] = useState<Filter>('ALL');
  const [selected, setSelected] = useState<string | null>(null);
  const counts = maturityCounts();
  const rows = CAPABILITIES.filter((c) => filter === 'ALL' || c.maturity === filter);
  const detail = selected ? CAPABILITIES.find((c) => c.id === selected) ?? null : null;

  return (
    <div className="page capabilities-page">
      <h2>Capabilities</h2>
      <p className="muted">
        The VERITX capability universe with truthful maturity state — mirrored
        from docs/product/capability-archaeology.yaml (28 audited records).
        Qualification determines what you can do with each feature; nothing
        is silently erased.
      </p>
      <div className="maturity-filter" role="group" aria-label="Filter by maturity">
        {(['ALL', ...MATURITIES] as Filter[]).map((m) => (
          <button
            key={m}
            className={filter === m ? 'btn active' : 'btn'}
            onClick={() => setFilter(m)}
            title={m === 'ALL' ? 'show every capability' : MATURITY_BLURB[m]}
          >
            {m === 'ALL' ? `All (${CAPABILITIES.length})` : `${m} (${counts[m]})`}
          </button>
        ))}
      </div>
      <table className="live-table capability-table">
        <thead>
          <tr>
            <th>Capability</th>
            <th>Status</th>
            <th>Intent</th>
            <th>Artifact</th>
            <th>Verifier</th>
            <th>Projection</th>
            <th>Executable</th>
            <th>Qualified</th>
            <th>Product</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr
              key={c.id}
              className={selected === c.id ? 'selected' : undefined}
              onClick={() => setSelected(c.id === selected ? null : c.id)}
              title={`${c.maturityNote}. Select for the capability page.`}
            >
              <td><strong>{c.name}</strong><br /><span className="muted">{c.id}</span></td>
              <td><span className={`maturity maturity-${c.maturity.toLowerCase().replace(/ /g, '-')}`}>{c.maturity}</span></td>
              <td>{c.stages.intent}</td>
              <td>{c.stages.artifact}</td>
              <td>{c.stages.verifier}</td>
              <td>{c.stages.projection}</td>
              <td>{c.stages.executable}</td>
              <td>{c.stages.qualified}</td>
              <td>{c.stages.product}</td>
              <td>{c.stages.evidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {detail && <CapabilityDetail cap={detail} />}

      <h3>Core product systems</h3>
      <p className="muted">
        Systems not represented as archaeology rows. States below are
        Studio-curated product-surface state, not registry authority.
      </p>
      <table className="live-table">
        <thead>
          <tr><th>System</th><th>Status</th><th>Note</th><th>Authority</th></tr>
        </thead>
        <tbody>
          {CORE_SYSTEMS.map((s) => (
            <tr key={s.id}>
              <td><strong>{s.name}</strong></td>
              <td><span className={`maturity maturity-${s.maturity.toLowerCase().replace(/ /g, '-')}`}>{s.maturity}</span></td>
              <td>{s.note}</td>
              <td className="muted">{s.authority}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>History (§43)</h3>
      <p className="muted">
        Historical comparisons stay visible as HISTORICAL with exact source
        commit/artifact. Historical measurements may be used as regression
        targets only after their workload/profile semantics are understood —
        never as current qualification.
      </p>
      <table className="live-table">
        <thead>
          <tr><th>Scope</th><th>Artifact</th><th>Note</th><th>Action</th></tr>
        </thead>
        <tbody>
          {HISTORY_ROWS.map((h) => (
            <tr key={h.artifact}>
              <td>{h.scope}</td>
              <td><code>{h.artifact}</code></td>
              <td>{h.note}</td>
              <td>Re-run under current canonical pipeline</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
