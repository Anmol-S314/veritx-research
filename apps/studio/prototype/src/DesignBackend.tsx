import { useEffect, useState } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason, type CanonicalRoute, type PreflightView, type RtlSourcesView, type UvmCollateral } from './gateway';
import { Badge, Button, Empty, Field, Notice, Properties, Section } from './ui';

/** Download one backend-generated text file without a server round trip. */
function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** `files[]` and the body fields share one order in the UVM view. */
const UVM_BODY_KEYS = ['dut_binding', 'tb_top', 'sequences', 'assertions', 'coverage'] as const;

function gateTone(state: string): 'green' | 'amber' | 'red' | 'neutral' {
  if (state === 'READY' || state === 'QUALIFIED') return 'green';
  if (state === 'REFUSED' || state === 'FAILED' || state === 'BLOCKED') return 'red';
  return 'amber';
}

/**
 * The compiler's expected route for one router pair. This is derived from the
 * frozen compile result, so it is evidence about the revision — not a UI guess
 * and not an observed packet path.
 */
export function RouteEvidence({ data }: { data: LoadedProject }) {
  const revisionId = data.detail.active_revision_id;
  const topology = data.topology;
  const routing = (data.compileResult?.groups?.routing ?? null) as {
    routing_classes?: string[]; default_class?: string | null;
    entries?: unknown[]; channel_hops?: unknown[]; available?: boolean;
  } | null;
  const classes = routing?.routing_classes ?? [];
  const routers = topology?.routers.map(router => router.router_id) ?? [];
  const [routingClass, setRoutingClass] = useState(classes[0] ?? '');
  const [src, setSrc] = useState(routers[0] ?? 0);
  const [dst, setDst] = useState(routers[routers.length - 1] ?? 0);
  const [route, setRoute] = useState<CanonicalRoute | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!revisionId || !classes.length) {
      setRoute(null); setError(''); setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError('');
    setRoute(null);
    gateway.route(revisionId, { routingClass: routingClass || undefined, src, dst })
      .then(value => { if (live) setRoute(value); })
      .catch(failure => { if (live) setError(gatewayReason(failure)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [revisionId, routingClass, src, dst, classes.length]);

  if (!revisionId) return <Section title="Compiler-derived route"><Empty title="No compiled revision">Compile a revision before asking the gateway to derive a route.</Empty></Section>;
  // No class means no route to walk. Asking the gateway anyway produced a raw
  // 400 on the page; the absence is a property of this revision, not a failure
  // of the request.
  if (!classes.length) return <Section title="Compiler-derived route" actions={<Badge tone="amber">no routing class</Badge>}>
    <Empty title="This revision declares no routing class">
      The compile result carries no routing class, so the gateway has no route to derive.
      Compile a fabric that declares one; reachability and the route walk stay unavailable until then.
    </Empty>
  </Section>;

  return <Section
    title="Compiler-derived route"
    actions={<Badge tone={route ? 'blue' : error ? 'amber' : 'neutral'}>{loading ? 'reading' : route ? `${route.routing_class} · ${route.routers.length - 1} hop${route.routers.length === 2 ? '' : 's'}` : 'no route'}</Badge>}
  >
    <p className="meta-line">The gateway walks the frozen compile result for one (routing class, source, destination) tuple. It is the expected route, not an observed packet path, latency measurement, or access-permission check.</p>
    <div className="toolbar toolbar-start">
      <Field label="Routing class">
        <select value={routingClass} onChange={event => setRoutingClass(event.target.value)} disabled={!classes.length}>
          {classes.length ? classes.map(value => <option key={value} value={value}>{value}</option>) : <option value="">No routing class in this revision</option>}
        </select>
      </Field>
      <Field label="Source router">
        <select value={src} onChange={event => setSrc(Number(event.target.value))}>
          {routers.map(value => <option key={value} value={value}>R{value}</option>)}
        </select>
      </Field>
      <Field label="Destination router">
        <select value={dst} onChange={event => setDst(Number(event.target.value))}>
          {routers.map(value => <option key={value} value={value}>R{value}</option>)}
        </select>
      </Field>
    </div>
    {error && <Notice tone="amber"><strong>The gateway refused this route.</strong> {error}</Notice>}
    {route && <>
      <Properties rows={[
        ['Routing class', <span className="mono" key="class">{route.routing_class}</span>],
        ['Path', <span className="mono" key="path">{route.routers.map(value => `R${value}`).join(' → ') || '—'}</span>],
        ['Terminates', route.terminates ? `Yes · ${route.terminal ?? 'terminal recorded'}` : `No · ${route.reason ?? 'no reason served'}`],
        ['Channel hops', String(route.hops.length)],
      ]} />
      {route.hops.length > 0 && <div className="table-scroll"><table><thead><tr><th>#</th><th>Channel</th><th>From</th><th>To</th></tr></thead><tbody>
        {route.hops.map((hop, index) => <tr key={`${hop.channel_id}-${index}`}>
          <td className="numeric">{index + 1}</td>
          <td className="mono">{hop.channel_id}</td>
          <td className="mono">R{hop.src_router} · p{hop.src_port}</td>
          <td className="mono">R{hop.dst_router} · p{hop.dst_port}</td>
        </tr>)}
      </tbody></table></div>}
    </>}
  </Section>;
}

/**
 * Delivery collateral the gateway can actually produce for this revision:
 * preflight gates, native UVM generation, and the Chipyard source inventory.
 * Every refusal is shown verbatim; nothing is generated in the browser.
 */
export function EngineeringHandoff({ data }: { data: LoadedProject }) {
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const [preflight, setPreflight] = useState<PreflightView | null>(null);
  const [preflightError, setPreflightError] = useState('');
  const [sources, setSources] = useState<RtlSourcesView | null>(null);
  const [sourceError, setSourceError] = useState('');
  const [uvm, setUvm] = useState<UvmCollateral | null>(null);
  const [uvmError, setUvmError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!revisionId) return;
    let live = true;
    setPreflightError('');
    gateway.preflight(revisionId)
      .then(value => { if (live) setPreflight(value); })
      .catch(failure => { if (live) setPreflightError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [revisionId]);

  useEffect(() => {
    let live = true;
    setSourceError('');
    gateway.rtlSources()
      .then(value => { if (live) setSources(value); })
      .catch(failure => { if (live) setSourceError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [projectId]);

  const generateUvm = async () => {
    if (!revisionId || busy) return;
    setBusy(true);
    setUvmError('');
    setUvm(null);
    try {
      setUvm(await gateway.generateUvm(revisionId));
    } catch (failure) {
      setUvmError(gatewayReason(failure));
    } finally {
      setBusy(false);
    }
  };

  const ready = preflight?.ready === true;
  const sourceAvailable = sources?.available === true;

  return <Section
    title="Backend collateral"
    actions={<Badge tone={uvm ? 'green' : preflightError || uvmError ? 'amber' : 'neutral'}>{uvm ? 'UVM generated' : preflight ? (ready ? 'preflight ready' : 'preflight refused') : 'reading'}</Badge>}
  >
    <p className="meta-line">These actions run on the gateway against the frozen revision. They are not simulated in the browser.</p>

    <div className="toolbar toolbar-start">
      <Button primary disabled={busy || !revisionId} onClick={generateUvm}>{busy ? 'Generating UVM…' : 'Generate UVM collateral'}</Button>
      {sourceAvailable && <a className="button" href={gateway.rtlSourcesArchiveUrl()} download>Download Chipyard source</a>}
      {sourceAvailable && revisionId && <a className="button" href={gateway.revisionChipyardSourceArchiveUrl(revisionId)} download>Download this revision’s source</a>}
    </div>

    {preflightError && <Notice tone="amber"><strong>Preflight unavailable.</strong> {preflightError}</Notice>}
    {preflight && <>
      <Properties rows={[
        ['Backend', <span className="mono" key="backend">{preflight.backend}</span>],
        ['Profile', preflight.backend_profile ?? '—'],
        ['Evidence tier', preflight.expected_evidence_tier ?? '—'],
        ['Route observation', preflight.route_observation_required ? 'Required' : 'Not required'],
        ['Conservation', preflight.conservation_required ? 'Required' : 'Not required'],
      ]} />
      <div className="table-scroll"><table><thead><tr><th>Gate</th><th>State</th><th>Detail</th></tr></thead><tbody>
        {preflight.gates.map(gate => <tr key={gate.gate}>
          <th>{gate.gate}</th>
          <td><Badge tone={gateTone(gate.state)}>{gate.state}</Badge></td>
          <td>{gate.reason ?? (gate.obligations_total !== undefined ? `${gate.obligations_passed ?? 0}/${gate.obligations_total} obligations` : '—')}</td>
        </tr>)}
      </tbody></table></div>
    </>}

    {sourceError && <Notice tone="amber"><strong>Source inventory unavailable.</strong> {sourceError}</Notice>}
    {sources && <Notice tone={sourceAvailable ? 'blue' : 'amber'}>
      <strong>Chipyard source · {sourceAvailable ? 'available' : 'not deliverable'}.</strong>{' '}
      {sourceAvailable
        ? `${sources.source_file_count} file(s) across ${sources.target_count} exporters. Source only; generation ${sources.generation}, simulation ${sources.simulation}, qualification ${sources.qualification}.`
        : sources.reason ?? 'The gateway did not name a reason.'}
    </Notice>}

    {uvmError && <Notice tone="red"><strong>UVM refused.</strong> {uvmError}</Notice>}
    {uvm && <>
      <Properties rows={[
        ['Fabric', `${uvm.fabric.family} · ${uvm.fabric.n_nodes} nodes · k=${uvm.fabric.k} · ${uvm.fabric.vc_count} VC(s)`],
        ['Routing classes', uvm.fabric.routing_classes.join(', ') || '—'],
        ['DUT binding scope', uvm.fabric.dut_binding_scope],
        ['DUT payload', `${uvm.fabric.dut_payload_bits} bits`],
        ['Derived from', uvm.fabric.derived_from.join(', ')],
      ]} />
      <div className="table-scroll"><table><thead><tr><th>File</th><th>Bytes</th><th>Action</th></tr></thead><tbody>
        {uvm.files.map((name, index) => {
          const key = UVM_BODY_KEYS[index];
          const body = key ? uvm[key] : '';
          return <tr key={name}>
            <th className="mono">{name}</th>
            <td className="numeric">{body.length.toLocaleString()}</td>
            <td><Button onClick={() => downloadText(name, body)}>Download</Button></td>
          </tr>;
        })}
      </tbody></table></div>
      <p className="meta-line">Generated from the compiled bundle ({String(uvm.identity.generator ?? 'generator')} {String(uvm.identity.generator_version ?? '')}). Collateral is not a simulation result, lint pass, or hardware qualification.</p>
    </>}
  </Section>;
}

/** Raw agent rows from the saved draft; fields other than clock_domain are preserved. */
type RawAgent = { kind?: string; count?: number; clock_domain?: string | null; [key: string]: unknown };

/**
 * Clock-domain intent is part of the agent inventory the compiler consumes.
 * Editing it saves the draft and compiles it, so the result is a new revision
 * (or a typed refusal) rather than a local-only label change.
 */
export function ClockDomainEditor({ data }: { data: LoadedProject }) {
  const { reload } = useProject();
  const agents = ((data.request as Record<string, unknown> | null)?.agents ?? []) as RawAgent[];
  const declared = [...new Set(['clk_fabric', ...agents
    .map(agent => agent.clock_domain)
    .filter((value): value is string => typeof value === 'string' && value.length > 0)])];
  const [drafts, setDrafts] = useState<string[]>(() => agents.map(agent => agent.clock_domain ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty = agents.some((agent, index) => (agent.clock_domain ?? '') !== drafts[index]);

  useEffect(() => {
    setDrafts(agents.map(agent => agent.clock_domain ?? ''));
    setError('');
    setNotice('');
    // Reset when the loaded draft/revision changes, not while the user types.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.draftMeta?.revisionToken]);

  if (!agents.length) return null;

  const save = async () => {
    if (busy || !dirty) return;
    setBusy(true);
    setError('');
    setNotice('');
    const projectId = data.detail.project.project_id;
    const next = {
      ...(data.request as Record<string, unknown>),
      agents: agents.map((agent, index) => ({ ...agent, clock_domain: drafts[index] || null })),
    };
    try {
      const saved = await gateway.putDraft(projectId, next, data.draftMeta?.revisionToken);
      try {
        const compiled = await gateway.compileProject(projectId, saved.revisionToken);
        setNotice(`Saved and compiled · ${compiled.revision_id ?? 'new revision'}${compiled.certificate?.overall ? ` · certificate ${compiled.certificate.overall}` : ''}.`);
      } catch (failure) {
        setError(`Draft saved, but compilation refused: ${gatewayReason(failure)}`);
      }
      reload();
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setBusy(false);
    }
  };

  return <Section
    title="Declared clock domains"
    actions={<Badge tone={dirty ? 'amber' : 'neutral'}>{dirty ? 'unsaved intent' : 'matches draft'}</Badge>}
  >
    <p className="meta-line">A clock domain is declared intent on each agent group. Saving compiles the draft; it does not perform CDC, timing, or reset analysis.</p>
    <div className="table-scroll"><table><thead><tr><th>Agent kind</th><th>Count</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
      {agents.map((agent, index) => <tr key={`${String(agent.kind)}-${index}`}>
        <th>{String(agent.kind ?? '—')}</th>
        <td className="numeric">{typeof agent.count === 'number' ? agent.count : '—'}</td>
        <td>
          <input
            aria-label={`Clock domain for ${String(agent.kind ?? 'agent')} ${index + 1}`}
            list="declared-clock-domains"
            value={drafts[index] ?? ''}
            placeholder="Not declared"
            onChange={event => setDrafts(current => current.map((value, at) => at === index ? event.target.value : value))}
          />
        </td>
        <td className="mono">{typeof agent.power_domain === 'string' ? agent.power_domain : 'Not declared'}</td>
      </tr>)}
    </tbody></table></div>
    <datalist id="declared-clock-domains">{declared.map(value => <option key={value} value={value} />)}</datalist>
    <div className="toolbar toolbar-start">
      <Button primary disabled={busy || !dirty} onClick={save}>{busy ? 'Saving & compiling…' : 'Save & compile clock intent'}</Button>
      <Button disabled={busy || !dirty} onClick={() => setDrafts(agents.map(agent => agent.clock_domain ?? ''))}>Discard</Button>
    </div>
    {notice && <Notice tone="blue">{notice}</Notice>}
    {error && <Notice tone="red">{error}</Notice>}
  </Section>;
}
