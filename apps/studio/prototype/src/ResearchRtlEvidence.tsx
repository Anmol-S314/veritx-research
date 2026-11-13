import { useEffect, useState } from 'react';
import { gateway, gatewayReason, type M5RtlPrototype, type M5RtlPrototypesResponse, type RtlSourcesView } from './gateway';
import { artifactSize, evidenceState, prototypeFileState } from './m5RtlRegistry';
import { Badge, Button, Notice, Properties, Section } from './ui';

/** Research RTL presence is a delivery-scope question, never a Flow decision.
 *  One module owns the catalog read and the evidence table. */
export function ResearchRtlEvidence() {
  const [protos, setProtos] = useState<M5RtlPrototypesResponse | null>(null);
  const [sources, setSources] = useState<RtlSourcesView | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true); setProtos(null); setError('');
    Promise.allSettled([gateway.rtlPrototypes(), gateway.rtlSources()])
      .then(([protoResult, sourceResult]) => {
        if (!live) return;
        if (protoResult.status === 'fulfilled') {
          const value = protoResult.value;
          setProtos(value);
          setSelected(previous => value.prototypes.some(row => row.topology_id === previous) ? previous : value.prototypes.find(row => row.required)?.topology_id ?? '');
        } else {
          setProtos(null); setSelected(''); setError(gatewayReason(protoResult.reason));
        }
        setSources(sourceResult.status === 'fulfilled' ? sourceResult.value : null);
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [refresh]);

  const rows = (items: M5RtlPrototype[]) => items.map(row => <tr key={row.topology_id} className={selected === row.topology_id ? 'is-selected' : ''}>
    <th><button className="delivery-row-select" aria-pressed={selected === row.topology_id} onClick={() => setSelected(row.topology_id)}>{row.label}<span className="mono">{row.topology_id}</span></button></th>
    <td>{prototypeFileState(row)}</td><td>{evidenceState(row.generation_completeness)}</td><td>{evidenceState(row.proof_status)}</td><td>{evidenceState(row.lint_status)} / {evidenceState(row.simulation_status)}</td><td>{evidenceState(row.qualification_status)}</td>
  </tr>);
  const selectedRow = protos?.prototypes.find(row => row.topology_id === selected);
  const required = protos?.prototypes.filter(row => row.required) ?? [];
  const optional = protos?.prototypes.filter(row => !row.required && row.catalog_family !== null) ?? [];
  const nonTarget = protos?.prototypes.filter(row => row.catalog_family === null) ?? [];

  return <Section title="Research RTL evidence" actions={<Button onClick={() => setRefresh(value => value + 1)} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh evidence'}</Button>}>
    <Notice tone="blue"><strong>Research Verilog presence, not product RTL.</strong> This table checks files in the configured Constellation source tree. It does not report the product's composed-family A1–A10 evidence or this revision's preview; those are separate tiers in the RTL &amp; implementation path above.</Notice>
    {sources && <Properties rows={[
      ['Source tree', sources.available ? 'Present' : 'Unavailable'],
      ['Exporters', `${sources.exporters_present ?? 0} / ${sources.exporters_total ?? sources.target_count}`],
      ['Parameterized core', sources.parameterized_core_present ? 'Present' : 'Absent'],
      ['Bound to this project', sources.matches_selected_project ? 'Yes' : 'No'],
      ['Generation / simulation / qualification', `${sources.generation} / ${sources.simulation} / ${sources.qualification}`],
    ]} />}
    <details className="delivery-details">
      <summary>Chipyard / Constellation source · all 14 topologies</summary>
      {sources?.available
        ? <><p>Native exporters, shared source, and KNCube implementation. Source only; no build or qualification.</p><a className="button" href={gateway.rtlSourcesArchiveUrl()} download>Download all 14 sources</a></>
        : sources
          ? <p>{sources.exporters_present ?? 0} of {sources.exporters_total ?? 14} family exporters are present across the repository and external trees. {sources.license_present === false ? 'The external source tree has no LICENSE file, so the archive is not assembled. ' : ''}{sources.reason ?? 'The source archive is not available.'}</p>
          : <p>The source inventory is not available in this gateway.</p>}
    </details>
    {loading && <p role="status">Loading current research RTL evidence…</p>}
    {error && <Notice tone="red">Research catalog unavailable: {error} Use Refresh evidence to retry. No offline snapshot is shown.</Notice>}
    {protos && <details className="research-rtl-fold">
      <summary>Target inventory · {protos.counts.required_present} present / {protos.counts.required_total} required</summary>
      <div className="toolbar">
        <Badge tone="neutral">Required targets · {protos.counts.required_present} present / {protos.counts.required_total}</Badge>
        <Badge tone="neutral">Missing or unknown · {protos.counts.required_missing_or_unknown}</Badge>
        <Badge tone="neutral">Optional · {protos.counts.optional_total} · non-target · {protos.counts.non_target_total}</Badge>
      </div>
      <div className="table-scroll"><table className="delivery-table"><thead><tr><th scope="col">Required target</th><th scope="col">File presence</th><th scope="col">Generation</th><th scope="col">Historical proof</th><th scope="col">Lint / simulation</th><th scope="col">Qualification</th></tr></thead><tbody>{rows(required)}</tbody></table></div>
      {optional.length > 0 && <details><summary>Optional targets ({optional.length})</summary><div className="table-scroll"><table className="delivery-table"><thead><tr><th>Target</th><th>File presence</th><th>Generation</th><th>Historical proof</th><th>Lint / simulation</th><th>Qualification</th></tr></thead><tbody>{rows(optional)}</tbody></table></div></details>}
      {nonTarget.length > 0 && <details><summary>Non-target entries ({nonTarget.length})</summary><div className="table-scroll"><table><thead><tr><th>Entry</th><th>Status</th></tr></thead><tbody>{nonTarget.map(row => <tr key={row.topology_id}><th>{row.label} <span className="mono">{row.topology_id}</span></th><td>{prototypeFileState(row)}</td></tr>)}</tbody></table></div></details>}
      {protos.artifacts.length > 0 && <details className="delivery-details"><summary>Generated evidence inventory</summary><p>These bounded metadata artifacts describe generated research output; they do not imply qualification.</p><ul className="delivery-artifacts">{protos.artifacts.map(file => <li key={file.artifact_id + file.name}><span className="mono delivery-filename" title={file.name}>{file.name}</span><span>{artifactSize(file.size_bytes)}</span><a className="button" href={gateway.rtlPrototypeArtifactUrl(file)} download>Download</a></li>)}</ul></details>}
      {selectedRow && <details className="delivery-details"><summary>{selectedRow.label} · {selectedRow.topology_id}</summary><p>{selectedRow.detail}</p><dl className="delivery-evidence"><dt>Source lineage</dt><dd>{evidenceState(selectedRow.lineage)}</dd><dt>Historical snapshot</dt><dd>{selectedRow.historical_snapshot.reported_verilog}; proof: {selectedRow.historical_snapshot.reported_proof}</dd><dt>Generation</dt><dd>{evidenceState(selectedRow.generation_completeness)}</dd><dt>Source reproduction</dt><dd>{evidenceState(selectedRow.source_reproduction_status)}</dd><dt>Project match</dt><dd>Not established.</dd></dl>
        <h4>Available artifacts</h4>{selectedRow.artifacts.length ? <ul className="delivery-artifacts">{selectedRow.artifacts.map(file => <li key={`${file.artifact_id}:${file.name}`}><span className="mono delivery-filename" title={file.name}>{file.name}</span><span>{artifactSize(file.size_bytes)}</span><a className="button" href={gateway.rtlPrototypeArtifactUrl(file)} download aria-label={`Download ${file.name} for ${selectedRow.label}`}>Download</a></li>)}</ul> : <p>No artifacts available.</p>}
      </details>}
    </details>}
  </Section>;
}
