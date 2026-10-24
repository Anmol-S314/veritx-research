import { useState } from 'react';
import { ANALYSIS_RUNS, analysisObservation } from './analysis';
import { Badge, Button, Empty, Inspector, Notice, PageLink, Properties, Section, downloadJson, type ViewProps } from './ui';
import { LiveRunArtifacts } from './LiveAnalysis';
import { useLoadedRun } from './project';

// Endpoint contracts read from the repository gateway (t3-topology/dse/veritx_dse/gateway/app.py).
// This prototype does not call them; the panels that would consume each one name it explicitly so a
// future wiring step has a fixed target instead of an invented shape.
const ENDPOINT = {
  artifacts: (run: string) => `GET /api/v1/runs/${run}/artifacts`,
  integrity: (run: string) => `GET /api/v1/runs/${run}/integrity`,
  evidence: (run: string) => `GET /api/v1/runs/${run}/evidence`,
  jobs: 'GET /api/v1/projects/{project_id}/jobs',
  job: 'GET /api/v1/jobs/{job_id}',
  revisionArtifacts: 'GET /api/v1/revisions/{revision_id}/artifacts',
};
// Response envelope of the artifact endpoint, with the bundle left absent because no bundle exists here.
const artifactContract = (run: string) => ({ contract_version: 1, run_id: run, bundle: null });

export function LogsArtifacts({ state, setState, notify }: ViewProps) {
  const [filter, setFilter] = useState('');
  const liveRun = useLoadedRun();
  const run = analysisObservation(state.analysisRun);
  const events = state.events.filter(e => e.toLowerCase().includes(filter.toLowerCase()));
  const output = state.lastExport;
  const bytes = output ? new TextEncoder().encode(output.content).length : 0;
  const truncated = state.events.length >= 100;
  return <div className="view-layout"><div className="view-main">
    <Notice tone="blue">{liveRun ? <><strong>Local activity + run {liveRun.detail.run_id.slice(0, 13)}…</strong> from the gateway.</> : <><strong>No run loaded</strong>; bundle panels stay empty.</>}</Notice>
    <div className="toolbar">
      <label className="search-field"><input aria-label="Filter local activity" placeholder="Filter local activity…" value={filter} onChange={e => setFilter(e.target.value)} /></label>
      <select aria-label="Select run for the artifact contract" value={state.analysisRun} onChange={e => setState(s => ({ ...s, analysisRun: e.target.value as typeof s.analysisRun }))}>{ANALYSIS_RUNS.map(r => <option key={r.id} value={r.id}>{r.id} · {r.workload}</option>)}</select>
      <Badge>{state.events.length} local events</Badge>
      <PageLink page="shared/jobs">Open Jobs, Problems &amp; Logs</PageLink>
    </div>
    <Section title="Local activity log" actions={<Button onClick={() => { downloadJson('local-activity-log.json', { schema: 'srota-studio-prototype/local-activity/v1', illustrative: true, backendJobLogs: 'Not available; no log-stream endpoint exists in the gateway contract', events: state.events }); notify('Exported the local activity log. No backend job logs exist to include.'); }}>Export local activity</Button>}>
      {events.length ? <div className="table-scroll"><table><thead><tr><th>Order</th><th>Event</th><th>Origin</th><th>Durability</th></tr></thead><tbody>
        {events.map((e, i) => <tr key={`${i}-${e}`}><td className="mono">{events.length - i}</td><td>{e}</td><td>Operator action in this browser</td><td>Local browser state</td></tr>)}
      </tbody></table></div> : <Empty title={filter ? 'No local event matches this filter' : 'No local activity recorded yet'}>Edits, reviews, and local exports append to this list. Nothing here comes from a backend job.</Empty>}
      <Properties rows={[[ 'Ordering basis', 'Insertion order, newest first' ], ['Timestamps', 'Not recorded; this prototype stores none rather than synthesizing one' ], ['Retained records', truncated ? 'Most recent 100 (older entries dropped)' : `${state.events.length} of 100 retained` ], ['Backend job logs', 'Unavailable — the gateway contract exposes job state, not a log stream' ]]} />
    </Section>
    {liveRun ? <>
      <Section title={`Run bundle · ${liveRun.detail.run_id.slice(0, 13)}…`} actions={<Badge tone="green">Gateway read</Badge>}>
        <LiveRunArtifacts run={liveRun} />
        <p>These paths and sha256 digests are the ones the run directory recorded. This surface still does not fetch file bodies or re-hash them; <a href="#/verify/checks">Local Checks</a> reads the backend's conservation and route-realization record instead.</p>
      </Section>
      <Section title="Integrity verification" actions={<Badge tone="amber">Read-only summary</Badge>}>
        <Properties rows={[[ 'Bundle id', <span className="mono">{liveRun.detail.bundle_id ?? '—'}</span> ], ['Packet conservation', liveRun.integrity?.packet_conservation ? 'Reported per stage; see Local Checks' : 'Not reported' ], ['Flit conservation', liveRun.integrity?.flit_conservation ? 'Reported per stage; see Local Checks' : 'Not reported' ], ['Route realization', liveRun.integrity?.route_realization?.status ?? 'Not reported' ], ['Re-hashed in this browser', 'No; digests are displayed as recorded' ], ['Backend refusals', 'Missing file, extra file, tampered file, manifest disagreeing with its own bundle_id, unimplemented schema' ]]} />
        <PageLink page="verify/checks">Open conservation and route-realization detail</PageLink>
      </Section>
    </> : <>
    <Section title={`Run bundle contract · ${run.id}`} actions={<Badge tone="amber">Not connected</Badge>}>
      <Properties rows={[[ 'Evaluated run', run.id ], ['Workload', run.workload ], ['Scope / window', run.scope ], ['Would be filled by', ENDPOINT.artifacts(run.id) ], ['Bundle present in this prototype', 'No; the fixture is an authored summary, not a run directory' ], ['bundle_id (path-independent content identity)', 'Not computed here' ], ['Per-file sha256', 'Not computed here' ], ['Selected-run fixture origin', 'Authored illustrative record, not tool output' ]]} />
      <div className="form-grid">
<pre className="code-preview">{JSON.stringify(artifactContract(run.id), null, 2)}</pre>
      </div>
      <table><thead><tr><th>Would-be panel</th><th>Endpoint</th><th>State here</th></tr></thead><tbody>
        <tr><th>Artifact file list</th><td className="mono">{ENDPOINT.artifacts(run.id)}</td><td><Badge tone="amber">Empty by design</Badge></td></tr>
        <tr><th>Backend evidence document</th><td className="mono">{ENDPOINT.evidence(run.id)}</td><td><Badge tone="amber">Not supplied</Badge></td></tr>
        <tr><th>Integrity verification</th><td className="mono">{ENDPOINT.integrity(run.id)}</td><td><Badge tone="amber">Not verified</Badge></td></tr>
        <tr><th>Job list for a project</th><td className="mono">{ENDPOINT.jobs}</td><td><Badge tone="amber">Not connected</Badge></td></tr>
        <tr><th>Single job status</th><td className="mono">{ENDPOINT.job}</td><td><Badge tone="amber">Not connected</Badge></td></tr>
        <tr><th>Revision artifacts</th><td className="mono">{ENDPOINT.revisionArtifacts}</td><td><Badge tone="amber">Not connected</Badge></td></tr>
      </tbody></table>
    </Section>
    </>}
    {!liveRun && <Section title="Integrity verification">
        <Properties rows={[[ 'Algorithm declared by the backend contract', 'sha256' ], ['Backend refusals', 'Missing file, extra file, tampered file, manifest disagreeing with its own bundle_id, or an unimplemented schema generation' ], ['Result in this prototype', 'Not evaluated — there is no bundle to verify' ], ['Local substitute', 'None; a digest of the prepared export would not be run-bundle integrity' ], ['Next action', 'Prepare a descriptive export, or connect a backend run bundle' ]]} />
        <Notice tone="amber">A local file hash is not run integrity.</Notice>
      </Section>}

    <Section title="Locally prepared export" actions={output ? <Badge tone="blue">Real local file</Badge> : undefined}>
      {output ? <>
        <Properties rows={[[ 'File name', output.name ], ['UTF-8 size', `${bytes.toLocaleString()} bytes` ], ['Prepared from', `${output.draft.id} · edit ${output.draft.revision}` ], ['Current draft', `${state.draft.id} · edit ${state.draft.revision}` ], ['Content identity', 'No sha256 recorded; the browser export path does not compute one' ], ['Generated hardware', 'None; this is a descriptive JSON export' ]]} />
        <div className="toolbar"><Button onClick={() => { downloadJson(output.name, JSON.parse(output.content)); notify('Downloaded the locally prepared descriptive export.'); }}>Download prepared file</Button><PageLink page="deliver/package">Inspect package manifest</PageLink><PageLink page="deliver/artifacts">Inspect artifact detail</PageLink></div>
      </> : <><Empty title="No local export prepared">This prototype can prepare one descriptive JSON file. Hardware-generation jobs and their artifacts are unavailable.</Empty><PageLink page="deliver/configuration" primary>Configure architecture export</PageLink></>}
    </Section>
    <Section title="What this surface cannot show">
      <ul>
        <li>Backend job logs: the gateway exposes job state and cancellation, not a log stream.</li>
        <li>Run artifacts, evidence, and integrity: no run bundle exists in this browser.</li>
        <li>Artifact hashes or bundle ids: computing them locally would misrepresent provenance.</li>
        <li>RTL, bitstream, or implementation artifacts: those capabilities are not established.</li>
      </ul>
    </Section>
  </div><Inspector title="Artifact & log boundary">
    <Badge tone="amber">Not connected</Badge>
    <Properties rows={[[ 'Local records shown', 'Activity list, prepared export' ], ['Backend-derived records shown', 'None' ], ['Run bundle in this browser', 'Absent' ], ['Evidence document', 'Not supplied' ], ['Integrity result', 'Not evaluated' ], ['Fabricated file list', 'Never' ], ['Download path', 'Browser download of a locally prepared JSON file' ]]} />
    <PageLink page="verify/evidence">Inspect evidence and claim scope</PageLink>
    <PageLink page="deliver/package">Inspect the prepared package</PageLink>
    <PageLink page="shared/projects">Review preserved local drafts</PageLink>
  </Inspector></div>;
}
