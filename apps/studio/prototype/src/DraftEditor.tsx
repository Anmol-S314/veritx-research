import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { gateway, gatewayReason } from './gateway';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { Badge, Button, Notice, Properties } from './ui';
import { FabricCanvas, parseFabricLinks, toggleFabricLink } from './FabricCanvas';
import { familyStatus, statusTone, useTopologyFamilies } from './capabilities';
import type { IntentSaveState } from './intent';
import { exactWireValue, parseAddressBigInt } from './agentMap';
import './draftWorkspace.css';

type Draft = Record<string, any>;
type DraftSectionId = 'topology' | 'physical' | 'srota' | 'router';


const FAMILIES: Record<string, { fields: string[]; enums?: Record<string, string[]>; defaults?: Record<string, any>; custom?: boolean }> = {
  mesh: { fields: ['side_length', 'concentration'], defaults: { side_length: 3, concentration: 1 } },
  concentrated_mesh: { fields: ['side_length', 'concentration'], defaults: { side_length: 2, concentration: 4 } },
  torus: { fields: ['side_length', 'concentration'], defaults: { side_length: 3, concentration: 1 } },
  flatfly: { fields: ['radix_per_dimension', 'dimension_count', 'concentration'], defaults: { radix_per_dimension: 4, dimension_count: 2, concentration: 1 } },
  fattree: { fields: ['switch_radix', 'level_count'], defaults: { switch_radix: 4, level_count: 2 } },
  gec: { fields: ['mode', 'grid_side_length', 'concentration', 'express_channel_groups_per_dimension', 'destinations_per_express_channel'], enums: { mode: ['mesh', 'express', 'multidrop', 'hybrid'] }, defaults: { mode: 'mesh', grid_side_length: 4, concentration: 1 } },
  ring_native: { fields: ['router_count'], defaults: { router_count: 64 } },
  qtree_native: { fields: ['radix', 'levels'], defaults: { radix: 4, levels: 3 } },
  tree4_native: { fields: ['radix', 'levels'], defaults: { radix: 4, levels: 3 } },
  fly_native: { fields: ['radix', 'levels'], defaults: { radix: 4, levels: 3 } },
  // Srota has typed booleans, enum sets, and a sorted island tuple, so it gets a dedicated form
  // instead of the numeric field loop. Defaults match the gateway's srota32 preset.
  srota: {
    fields: [],
    custom: true,
    defaults: {
      side_length: 4, concentration: 2, mecs_row: true, mecs_col: true, drop_latency: 1,
      planes: ['d', 't'], island_columns: [], path_shapes: ['row'], vc_policy: 'none',
      sidebuf_enable: true, sidebuf_watermark: 6, tel_period: 4, tel_latency: 8,
    },
  },
};
const SROTA_PLANES = [['d', 'Plane D · data'], ['c', 'Plane C · control'], ['t', 'Plane T · telemetry']] as const;
const SROTA_SHAPES = [['row', 'Row-first'], ['column', 'Column-first'], ['valiant', 'Valiant']] as const;
const SROTA_VC_POLICIES = ['none', 'shape', 'rank', 'oneshape'];
const SROTA_REQUIRED = ['side_length', 'concentration', 'mecs_row', 'mecs_col', 'drop_latency', 'planes', 'path_shapes', 'vc_policy', 'sidebuf_enable', 'tel_period', 'tel_latency'];
const AGENT_KINDS = ['compute_tile', 'hbm_controller', 'nic'];
const DEP_KINDS = ['blocking', 'ordering', 'independent'];
const GRAPH_KINDS = ['custom', 'anynet'];

function pickFamily(kind: string, previous: Draft): Draft {
  const spec = FAMILIES[kind];
  if (!spec) return { kind };
  const next: Draft = { kind, ...(spec.defaults ?? {}) };
  for (const field of spec.fields) if (previous[field] !== undefined) next[field] = previous[field];
  return next;
}

const toggleList = (list: unknown, value: string) => {
  const items = Array.isArray(list) ? list.map(String) : [];
  return items.includes(value) ? items.filter(item => item !== value) : [...items, value];
};

const FIELD_LABELS: Record<string, string> = {
  side_length: 'Routers per side', concentration: 'Endpoints per router', radix_per_dimension: 'Radix per dimension',
  dimension_count: 'Dimensions', switch_radix: 'Switch radix', level_count: 'Level count', mode: 'Express mode',
  grid_side_length: 'Grid side length', express_channel_groups_per_dimension: 'Express groups per dimension',
  destinations_per_express_channel: 'Destinations per express group', router_count: 'Router count',
  radix: 'Radix', levels: 'Levels', clock_freq_mhz: 'Clock frequency (MHz)', data_width: 'Data width (bits)',
  num_power_domains: 'Power domains', process_node_nm: 'Process node (nm)', link_width: 'Link width (bits)',
  drop_latency: 'Drop latency (cycles)', sidebuf_watermark: 'Side-buffer watermark (flits)',
  tel_period: 'Telemetry window (cycles)', tel_latency: 'Telemetry staleness (cycles)',
  'input buffer depth (flits / VC)': 'Buffer depth (flits/VC)', 'credit return latency (cycles)': 'Credit return latency',
  'allocator iterations': 'Allocator iterations', 'route compute cycles': 'Route compute (cycles)',
  'VC allocation cycles': 'VC allocation (cycles)', 'switch allocation cycles': 'Switch allocation (cycles)',
  'switch traversal cycles': 'Switch traversal (cycles)',
};
const FAMILY_LABELS: Record<string, string> = {
  mesh: 'Mesh', concentrated_mesh: 'Concentrated mesh', torus: 'Torus', flatfly: 'Flatfly', fattree: 'Fat-tree',
  gec: 'GEC', ring_native: 'Ring', qtree_native: 'QTree', tree4_native: 'Tree4', fly_native: 'Fly', srota: 'Srota', explicit: 'Explicit graph',
};
const fieldLabel = (key: string) => FIELD_LABELS[key]
  ?? Object.entries(FIELD_LABELS).find(([name]) => name.replaceAll('_', ' ').toLowerCase() === key.toLowerCase())?.[1]
  ?? key.replaceAll('_', ' ');
const familyLabel = (key: string) => FAMILY_LABELS[key] ?? key.replaceAll('_', ' ');

const numberField = (label: string, value: number | null | undefined, onChange: (next: number | null) => void, hint?: string, readOnly = false, onReveal?: (name: string) => void) => (
  <label className="field" key={label}><span>{fieldLabel(label)}</span>
    <input type="number" aria-label={fieldLabel(label)} readOnly={readOnly} onFocus={() => onReveal?.(fieldLabel(label))} value={value ?? ''} onChange={e => { const raw = e.target.value; if (raw === '') { onChange(null); return; } const next = Number(raw); if (Number.isFinite(next)) onChange(next); }} />
    {hint && <small>{hint}</small>}
  </label>
);

const reqInt = (value: string, label: string, minimum = 0) => {
  const next = Number(value);
  if (value.trim() === '' || !Number.isSafeInteger(next) || next < minimum) throw new Error(`${label} must be an integer >= ${minimum}.`);
  return next;
};
const reqAddress = (value: string, label: string, minimum = 0n) => {
  const next = parseAddressBigInt(value);
  if (next === null || next < minimum) throw new Error(`${label} must be an unsigned 64-bit integer >= ${minimum}.`);
  return exactWireValue(next);
};
const textRow = (label: string, value: string, onChange: (next: string) => void) => (
  <label className="field"><span>{label}</span><input value={value} onChange={e => onChange(e.target.value)} /></label>
);

export function DraftEditor({ project, onDirty, embedded = false, onSaveState, tuning = false, onCompiled, onContinue }: {
  project: LoadedProject;
  onDirty?: (dirty: boolean) => void;
  embedded?: boolean;
  onSaveState?: (state: IntentSaveState) => void;
  tuning?: boolean;
  onCompiled?: () => void;
  onContinue?: () => void;
}) {
  const { reload } = useProject();
  const draft = useMemo(() => (project.request as Draft | null) ?? null, [project.request]);
  const [topology, setTopology] = useState<Draft>({});
  const [physical, setPhysical] = useState<Draft>({});
  const [noc, setNoc] = useState<Draft>({});
  const [agents, setAgents] = useState<Draft[]>([]);
  const [ranges, setRanges] = useState<Draft[]>([]);
  const [dependencies, setDependencies] = useState<Draft[]>([]);
  const [graph, setGraph] = useState<Draft>({ name: '', kind: 'custom', nodes: '', links: '', bandwidth: '', latency: '' });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'save' | 'compile' | null>(null);
  const [pendingCompile, setPendingCompile] = useState(false);
  const version = useRef(project.draftMeta?.revisionToken);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ routers?: number; channels?: number } | null>(null);
  const [canonical, setCanonical] = useState<Draft | null>(null);
  const [seeded, setSeeded] = useState(false);
  const saveRef = useRef<() => void>(() => {});
  const familyProbe = useTopologyFamilies();
  // An editor-local change is not a saved draft. Compile reads the server draft, so the parent
  // disables compile until these edits are validated and saved.
  const unsaved = touched || (seeded && canonical !== null);
  useEffect(() => { onDirty?.(unsaved); }, [unsaved, onDirty]);
  const revealSection = (name: string) => {
    const order: DraftSectionId[] = [section, ...(['topology', 'physical', 'srota', 'router'] as DraftSectionId[]).filter(id => id !== section)];
    const lower = name.toLowerCase();
    for (const id of order) {
      const fields = SECTION_FIELDS.get(id) ?? [];
      if (!fields.some(field => field.toLowerCase() === lower)) continue;
      if (id === 'srota' && topology.kind !== 'srota') continue;
      setSection(id);
      return;
    }
  };
  useEffect(() => {
    if (!draft) return;
    setSeeded(!draft.topology && (!!project.topology || !!draft.noc_config?.topology_family));
    // Keep the family the user picked: a reload may return a draft whose topology
    // block is migrated (no `kind` key) and must not silently revert the choice.
    setTopology(previous => {
      if (!draft.topology) {
        const compiled = project.topology;
        if (compiled) {
          // Legacy drafts carry no fabric declaration, yet the compiled revision does. Seed the
          // editor from that revision instead of showing blank fields the user cannot reconcile.
          const family = compiled.family;
          if (!FAMILIES[family]) return { ...previous, kind: family };
          const coordinates = compiled.routers.map(router => router.coordinates ?? []).filter(value => value.length >= 2);
          const side = coordinates.length
            ? Math.max(...coordinates.map(value => value[0] + 1), ...coordinates.map(value => value[1] + 1))
            : Math.round(Math.sqrt(compiled.routers.length));
          // Seed only values the compiled revision actually exposes. Inventing the
          // remaining dimensions from family defaults would silently rewrite the design.
          if (family === 'srota') return { kind: 'srota', side_length: side };
          const next: Draft = { ...previous, kind: family };
          for (const field of FAMILIES[family].fields) {
            if (field === 'side_length') next.side_length = side;
            else if (field === 'concentration') next.concentration = draft.noc_config?.concentration ?? FAMILIES[family].defaults?.concentration ?? 1;
          }
          if (family === 'ring_native') next.router_count = compiled.routers.length;
          return next;
        }
        // A legacy draft can name a family without storing any dimensions. Keep the family visible
        // and seed only the documented concentration default; leave dimensions empty because the
        // compiler derives them, so inventing a side length here would silently change the design.
        const legacyFamily = draft.noc_config?.topology_family as string | undefined;
        if (legacyFamily) {
          const spec = FAMILIES[legacyFamily];
          return { ...previous, kind: legacyFamily, ...(spec?.defaults?.concentration !== undefined ? { concentration: spec.defaults.concentration } : {}) };
        }
        return previous;
      }
      const stored = { ...draft.topology };
      const kind = (stored.kind as string | undefined) ?? previous.kind ?? (draft.noc_config?.topology_family as string | undefined) ?? '';
      return kind ? { kind, ...stored } : stored;
    });
    setPhysical({ ...(draft.physical ?? {}) });
    // v2 drafts keep NOC settings in `noc_config`; v4 renamed it to `noc_controls`.
    setNoc({ ...((draft.noc_controls ?? draft.noc_config) ?? {}) });
    setAgents((draft.agents ?? []).map((a: Draft) => ({ ...a })));
    setRanges(((draft.address_map?.ranges ?? []) as Draft[]).map(r => ({
      name: r.name ?? '', base: String(r.base ?? ''), size: String(r.size ?? r.size_bytes ?? ''),
      target: String(r.target_agent_idx ?? (typeof r.target === 'number' ? r.target : 0)),
    })));
    setDependencies(((draft.dependencies ?? []) as Draft[]).map(d => ({
      source: d.source ?? d.from ?? '', target: d.target ?? d.to ?? '', kind: d.kind ?? 'blocking',
    })));
    const stored = (draft.topology as Draft | undefined)?.graph ?? draft.explicit_topology;
    if (stored) setGraph({
      name: stored.name ?? '', kind: stored.kind ?? 'custom', nodes: String(stored.nodes ?? ''),
      links: ((stored.links ?? []) as unknown[]).map(l => Array.isArray(l) ? `${l[0]} ${l[1]}` : String(l)).join('\n'),
      bandwidth: String(stored.link_attrs?.bandwidth_GBs ?? ''), latency: String(stored.link_attrs?.latency_ns ?? ''),
    });
    setPreview(null); setError(null); setCanonical(null); setTouched(false);
    setPendingCompile(false); version.current = project.draftMeta?.revisionToken;
  }, [draft]);

  const canValidate = topology.kind === 'explicit' || !!FAMILIES[topology.kind as string];
  const [section, setSection] = useState<DraftSectionId>('topology');
  const sectionPane = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    onSaveState?.({
      dirty: unsaved || !!canonical,
      valid: !!canonical && canValidate,
      busy: busy !== null,
      error: error ?? '',
      save: () => saveRef.current(),
    });
  }, [unsaved, canonical, canValidate, busy, error, onSaveState]);

  if (!draft) return <div className="section"><div className="section-heading"><h2>Draft editor</h2></div><Notice tone="amber">No draft request to edit.</Notice></div>;

  const nocKey = draft.noc_controls !== undefined ? 'noc_controls' : 'noc_config';
  const isExplicit = topology.kind === 'explicit';
  // v4 carries the graph in `topology.graph`; v3 carries it in `explicit_topology`.
  const explicitKey = draft.topology !== undefined || (draft.schema_version ?? 4) >= 4 ? 'topology' : 'explicit_topology';

  const buildGraph = (): Draft => {
    if (!graph.name.trim()) throw new Error('Explicit graph needs a name.');
    if (!GRAPH_KINDS.includes(graph.kind)) throw new Error('Explicit graph kind must be custom or anynet.');
    const nodes = reqInt(String(graph.nodes), 'Explicit graph nodes', 1);
    const links = String(graph.links).split('\n').map(line => line.trim()).filter(Boolean).map((line, i) => {
      const parts = line.split(/\s+/);
      if (parts.length !== 2) throw new Error(`Explicit graph link ${i + 1}: expected 'src dst'.`);
      return [reqInt(parts[0], `Explicit graph link ${i + 1} source`), reqInt(parts[1], `Explicit graph link ${i + 1} destination`)];
    });
    if (!links.length) throw new Error('Explicit custom/anynet graphs require at least one link.');
    const bandwidth = Number(graph.bandwidth), latency = Number(graph.latency);
    if (!Number.isFinite(bandwidth) || bandwidth <= 0 || !Number.isFinite(latency) || latency <= 0) throw new Error('Explicit graph link_attrs needs positive bandwidth_GBs and latency_ns.');
    return { name: graph.name.trim(), kind: graph.kind, nodes, links, link_attrs: { bandwidth_GBs: bandwidth, latency_ns: latency } };
  };

  const merged = (withTopology: boolean): Draft => {
    const builtRanges = ranges.filter(r => r.name.trim() || String(r.base).trim() || String(r.size).trim()).map((r, i) => {
      if (!r.name.trim()) throw new Error(`Address range ${i + 1}: name is required.`);
      return { name: r.name.trim(), base: reqAddress(String(r.base), `Address range ${i + 1} base`), size: reqAddress(String(r.size), `Address range ${i + 1} size`, 1n), target_agent_idx: reqInt(String(r.target), `Address range ${i + 1} target`) };
    });
    const builtDependencies = dependencies.filter(d => d.source.trim() || d.target.trim()).map((d, i) => {
      if (!d.source.trim() || !d.target.trim()) throw new Error(`Dependency ${i + 1}: source and target are required.`);
      if (!DEP_KINDS.includes(d.kind)) throw new Error(`Dependency ${i + 1}: kind must be blocking, ordering, or independent.`);
      return { source: d.source.trim(), target: d.target.trim(), kind: d.kind };
    });
    const base: Draft = { ...draft, physical, agents, [nocKey]: noc };
    if (draft.address_map !== undefined || builtRanges.length) base.address_map = { ranges: builtRanges };
    if (draft.dependencies !== undefined || builtDependencies.length) base.dependencies = builtDependencies;
    if (isExplicit) {
      const graphDoc = buildGraph();
      if (explicitKey === 'topology') base.topology = { kind: 'explicit', graph: graphDoc };
      else base.explicit_topology = graphDoc;
    } else if (withTopology && draft.topology !== undefined) base.topology = topology;
    return base;
  };

  const validate = async (): Promise<Draft> => {
    if (!isExplicit) {
      const spec = FAMILIES[topology.kind as string];
      if (!spec) throw new Error('Choose a topology family before validating.');
      const required = topology.kind === 'srota' ? SROTA_REQUIRED : spec.fields.filter(field => !(topology.kind === 'gec' && topology.mode === 'mesh' && ['express_channel_groups_per_dimension', 'destinations_per_express_channel'].includes(field)));
      const missing = required.filter(field => topology[field] === undefined || topology[field] === null || topology[field] === '');
      if (missing.length) throw new Error(`Declare ${missing.join(', ')} before validating.`);
    }
    const response = await gateway.topologyPreview(project.detail.project.project_id, merged(false), isExplicit ? (explicitKey === 'topology' ? { kind: 'explicit', graph: buildGraph() } : topology) : topology);
    if (!response.request) throw new Error('The gateway returned no canonical draft. Nothing was saved.');
    return response.request;
  };

  const previewTopology = async () => {
    setBusy('preview'); setError(null);
    try {
      const canonical = await validate();
      const topo = (canonical.topology ?? {}) as Draft;
      setPreview({
        routers: topo.routers?.length ?? topo.router_count ?? topo.side_length,
        channels: topo.channels?.length,
      });
      setCanonical(canonical);
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy('save'); setError(null);
    try {
      if (!canonical) throw new Error('Validate the current edits before saving.');
      const current = await gateway.projectDraft(project.detail.project.project_id);
      if (project.draftMeta?.revisionToken && current.revisionToken !== project.draftMeta.revisionToken) throw new Error('Draft changed on the server. Reload and review before saving.');
      await gateway.putDraft(project.detail.project.project_id, canonical, project.draftMeta?.revisionToken);
      reload();
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(null);
    }
  };

  const saveAndCompile = async () => {
    if (busy) return;
    if (!version.current) { setError('The draft version is missing. Reopen the project before saving.'); return; }
    let saved = false;
    setBusy('preview'); setError(null);
    try {
      const canonical = await validate();
      setBusy('save');
      const result = await gateway.putDraft(project.detail.project.project_id, canonical, version.current);
      version.current = result.revisionToken;
      saved = true; setPendingCompile(true);
      if (!version.current) throw new Error('The gateway returned no saved draft version. Reopen this project.');
      setBusy('compile');
      await gateway.compileProject(project.detail.project.project_id, version.current);
      onCompiled?.(); reload();
    } catch (caught) {
      setError(`${saved ? 'Draft saved; compilation did not finish. ' : ''}${gatewayReason(caught)}`);
    } finally { setBusy(null); }
  };

  const dirty = touched;
  const ready = !unsaved && !pendingCompile && !project.draftMeta?.dirty && !!project.detail.active_revision_id && !busy && !error;
  const legacy = !draft.topology;
  const authorable = !!FAMILIES[topology.kind as string];
  saveRef.current = save;
  const selectedFamily = familyStatus(familyProbe.families, topology.kind as string | undefined);
  const derivedVc = (project.detail.active_revision?.design as Record<string, any> | undefined)?.locked_derived?.vc_count as number | undefined;
  const SECTION_FIELDS = new Map<DraftSectionId, string[]>([
    ['topology', ['Topology family', 'Routers per side', 'Endpoints per router', 'Radix per dimension', 'Dimensions', 'Switch radix', 'Level count', 'Router count', 'Radix', 'Levels']],
    ['physical', ['Clock frequency (MHz)', 'Data width (bits)', 'Power domains', 'Process node (nm)']],
    ['router', ['Link width (bits)', 'Buffer depth (flits/VC)', 'Credit return latency', 'Allocator iterations', 'Route compute (cycles)', 'VC allocation (cycles)', 'Switch allocation (cycles)', 'Switch traversal (cycles)', 'Arbitration']],
    ['srota', ['VC policy', 'Island columns', 'Drop latency (cycles)', 'Side-buffer watermark (flits)', 'Telemetry window (cycles)', 'Telemetry staleness (cycles)']],
  ]);
  const sections: ReadonlyArray<{ id: DraftSectionId; label: string }> = [
    { id: 'topology', label: 'Topology & sizing' },
    { id: 'physical', label: 'Physical assumptions' },
    ...(topology.kind === 'srota' ? [{ id: 'srota' as const, label: 'Srota intent' }] : []),
    { id: 'router', label: 'Router & pipeline' },
  ];
  const changeSection = (next: DraftSectionId) => {
    if (next === section) return;
    setSection(next);
    sectionPane.current?.focus({ preventScroll: true });
  };
  const sectionKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % sections.length;
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index + sections.length - 1) % sections.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = sections.length - 1;
    else return;
    event.preventDefault();
    changeSection(sections[next].id);
    sectionRefs.current[next]?.focus({ preventScroll: true });
  };
  const canvasCount = Math.max(0, Math.min(256, Number.parseInt(graph.nodes, 10) || 0));
  const canvasLinks = parseFabricLinks(String(graph.links));
  const invalidate = () => { setCanonical(null); setPreview(null); setTouched(true); };
  const canvasToggle = (a: number, b: number) => {
    const next = toggleFabricLink(canvasLinks, a, b);
    setGraph(value => ({ ...value, links: next.map(([x, y]) => `${x} ${y}`).join('\n') }));
    invalidate();
  };

  return <div className={`draft-panel${embedded ? ' embedded' : ''}${tuning ? ' tuning' : ''}`} onChange={() => { setCanonical(null); setPreview(null); setTouched(true); }}>
    <fieldset className="draft-controls" disabled={busy !== null}>
    {!tuning && <div className="toolbar" style={{ marginBottom: 10 }}>
      <span className="muted">{canonical ? (dirty || seeded ? 'Validated; review and save' : 'Validated; nothing to save') : 'Validate the fabric before saving'}{embedded ? ' · save in the Intent bar' : ' · compile in step 3'}</span>
      <Button disabled={busy !== null || !canValidate} title={canValidate ? undefined : 'Choose an authorable topology family first'} onClick={previewTopology}>{busy === 'preview' ? 'Validating…' : 'Validate topology'}</Button>
      {!embedded && <Button primary disabled={busy !== null || !canonical || !canValidate} title={!canValidate ? 'Choose an authorable topology family first' : canonical ? undefined : 'Validate the fabric first'} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save draft'}</Button>}
    </div>}

    {legacy && <Notice tone="blue"><strong>Schema v{draft.schema_version ?? 2} draft:</strong> {project.topology
      ? <>no fabric block is stored; the form is seeded from compiled revision <span className="mono">{project.detail.active_revision_id}</span> ({topology.kind}).</>
      : topology.kind
        ? <>this draft stores the family (<code>{topology.kind}</code>) but not its dimensions; declare them below. Validating a topology upgrades it to v4.</>
        : <>this draft stores no fabric declaration; choose a family below. Validating a topology upgrades it to v4.</>}</Notice>}
    {topology.kind && !authorable && !isExplicit && <Notice tone="amber">The <code>{topology.kind}</code> family is not authorable in this editor yet. The existing declaration is preserved; validating is disabled rather than sending guessed fields.</Notice>}
    <div className="draft-workspace">
      <nav className="draft-sections" role="tablist" aria-orientation="vertical" aria-label="Draft sections">
        {sections.map((item, index) => <button
          key={item.id}
          type="button"
          role="tab"
          id={`draft-section-${item.id}`}
          aria-controls="draft-section-panel"
          aria-selected={section === item.id}
          tabIndex={section === item.id ? 0 : -1}
          ref={element => { sectionRefs.current[index] = element; }}
          onClick={() => changeSection(item.id)}
          onKeyDown={event => sectionKey(event, index)}
        >{item.label}</button>)}
      </nav>
      <div className="draft-section-panel" id="draft-section-panel" role="tabpanel" aria-labelledby={`draft-section-${section}`} ref={sectionPane} tabIndex={0}>
        {section === 'topology' && <div className="form-grid">
          <label className="field"><span>Topology family</span>
            <select disabled={tuning} value={topology.kind ?? ''} onFocus={() => revealSection('Topology family')} onChange={e => { setTopology(t => pickFamily(e.target.value, t)); }}>
              {topology.kind && !FAMILIES[topology.kind] && topology.kind !== 'explicit' && <option value={topology.kind}>{familyLabel(topology.kind)} (not editable here)</option>}
              {Object.keys(FAMILIES).map(family => <option key={family} value={family}>{familyLabel(family)}</option>)}
              <option value="explicit">{familyLabel('explicit')}</option>
            </select>
          </label>
          {(FAMILIES[topology.kind as string]?.fields ?? []).map(key => {
            const spec = FAMILIES[topology.kind as string];
            const options = spec?.enums?.[key];
            if (topology.kind === 'gec' && topology.mode === 'mesh' && ['express_channel_groups_per_dimension', 'destinations_per_express_channel'].includes(key)) return null;
            if (options) return <label className="field" key={key}><span>{key}</span>
              <select value={String(topology[key] ?? options[0])} onFocus={() => revealSection(key)} onChange={e => setTopology(t => key === 'mode' && e.target.value === 'mesh' ? { ...t, mode: 'mesh', express_channel_groups_per_dimension: null, destinations_per_express_channel: null } : { ...t, [key]: e.target.value })}>
                {options.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>;
            const fixedNative = ['qtree_native', 'tree4_native', 'fly_native'].includes(topology.kind) && ['radix', 'levels'].includes(key);
            return numberField(key.replace(/_/g, ' '), topology[key], value => { setTopology(t => ({ ...t, [key]: value })); }, fixedNative ? 'Fixed by the native implementation; router controls remain editable.' : undefined, fixedNative, revealSection);
          })}
        </div>}
        {section === 'physical' && <div className="form-grid">
          {numberField('clock_freq_mhz', physical.clock_freq_mhz, value => setPhysical(p => ({ ...p, clock_freq_mhz: value })), undefined, false, revealSection)}
          {numberField('data_width', physical.data_width, value => setPhysical(p => ({ ...p, data_width: value })), undefined, false, revealSection)}
          {numberField('num_power_domains', physical.num_power_domains, value => setPhysical(p => ({ ...p, num_power_domains: value })), undefined, false, revealSection)}
          {numberField('process_node_nm', physical.process_node_nm, value => setPhysical(p => ({ ...p, process_node_nm: value })), undefined, false, revealSection)}
        </div>}
        {section === 'srota' && topology.kind === 'srota' && <>
          <div className="section-heading"><h2>Srota intent</h2><Badge tone="blue">typed fabric</Badge></div>
          <div className="form-grid">
            {numberField('side_length', topology.side_length, value => setTopology(t => ({ ...t, side_length: value })), 'Router grid side k (k × k)', false, revealSection)}
            {numberField('concentration', topology.concentration, value => setTopology(t => ({ ...t, concentration: value })), 'Endpoints per router; minimum 1', false, revealSection)}
            {numberField('drop_latency', topology.drop_latency, value => setTopology(t => ({ ...t, drop_latency: value })), 'Cycles', false, revealSection)}
            {numberField('sidebuf_watermark', topology.sidebuf_watermark, value => setTopology(t => ({ ...t, sidebuf_watermark: value })), 'Flits', false, revealSection)}
            {numberField('tel_period', topology.tel_period, value => setTopology(t => ({ ...t, tel_period: value })), 'Telemetry window (cycles)', false, revealSection)}
            {numberField('tel_latency', topology.tel_latency, value => setTopology(t => ({ ...t, tel_latency: value })), 'Telemetry staleness (cycles)', false, revealSection)}
          </div>
          <div className="dimension-row"><span>Express layer and router</span><div className="actions">
            <label className="check-chip"><input type="checkbox" checked={!!topology.mecs_row} onChange={e => setTopology(t => ({ ...t, mecs_row: e.target.checked }))} />Row MECS</label>
            <label className="check-chip"><input type="checkbox" checked={!!topology.mecs_col} onChange={e => setTopology(t => ({ ...t, mecs_col: e.target.checked }))} />Column MECS</label>
            <label className="check-chip"><input type="checkbox" checked={!!topology.sidebuf_enable} onChange={e => setTopology(t => ({ ...t, sidebuf_enable: e.target.checked }))} />Side buffer</label>
          </div></div>
          <div className="dimension-row"><span>Planes</span><div className="actions">
            {SROTA_PLANES.map(([value, label]) => <label key={value} className="check-chip"><input type="checkbox" checked={(topology.planes ?? []).includes(value)} onChange={() => setTopology(t => ({ ...t, planes: toggleList(t.planes, value) }))} />{label}</label>)}
          </div></div>
          <div className="dimension-row"><span>Path shapes</span><div className="actions">
            {SROTA_SHAPES.map(([value, label]) => <label key={value} className="check-chip"><input type="checkbox" checked={(topology.path_shapes ?? []).includes(value)} onChange={() => setTopology(t => ({ ...t, path_shapes: toggleList(t.path_shapes, value) }))} />{label}</label>)}
          </div></div>
          <div className="form-grid">
            <label className="field"><span>VC policy</span>
              <select aria-label="srota vc policy" value={String(topology.vc_policy ?? 'none')} onFocus={() => revealSection('srota vc policy')} onChange={e => setTopology(t => ({ ...t, vc_policy: e.target.value }))}>
                {SROTA_VC_POLICIES.map(policy => <option key={policy} value={policy}>{policy}</option>)}
              </select>
            </label>
            <label className="field"><span>Island columns</span>
              <input aria-label="srota island columns" placeholder="none" value={(topology.island_columns ?? []).join(', ')} onFocus={() => revealSection('srota vc policy')} onChange={e => setTopology(t => ({ ...t, island_columns: e.target.value.split(',').map(value => value.trim()).filter(Boolean).map(Number).filter(Number.isFinite) }))} />
              <small>Comma-separated router columns; islands require both MECS directions.</small>
            </label>
          </div>
        </>}
        {section === 'router' && <div className="form-grid">
          {numberField('link_width', noc.link_width, value => { setNoc(n => ({ ...n, link_width: value })); }, undefined, false, revealSection)}
          {nocKey === 'noc_controls' ? <>
            {numberField('input buffer depth (flits / VC)', noc.input_buffer_depth_flits_per_vc, value => { setNoc(n => ({ ...n, input_buffer_depth_flits_per_vc: value })); }, '1–64; applies per virtual channel', false, revealSection)}
            {numberField('credit return latency (cycles)', noc.credit_return_latency_cycles, value => { setNoc(n => ({ ...n, credit_return_latency_cycles: value })); }, '0–16', false, revealSection)}
            {numberField('allocator iterations', noc.allocator_iterations, value => { setNoc(n => ({ ...n, allocator_iterations: value })); }, '1–16', false, revealSection)}
            {numberField('route compute cycles', noc.route_compute_cycles, value => { setNoc(n => ({ ...n, route_compute_cycles: value })); }, '1–16', false, revealSection)}
            {numberField('VC allocation cycles', noc.vc_alloc_cycles, value => { setNoc(n => ({ ...n, vc_alloc_cycles: value })); }, '1–16', false, revealSection)}
            {numberField('switch allocation cycles', noc.switch_alloc_cycles, value => { setNoc(n => ({ ...n, switch_alloc_cycles: value })); }, '1–16', false, revealSection)}
            {numberField('switch traversal cycles', noc.switch_traversal_cycles, value => { setNoc(n => ({ ...n, switch_traversal_cycles: value })); }, '1–16', false, revealSection)}
          </> : <p className="meta-line">Buffer depth and router-pipeline controls are v4 <code>noc_controls</code> fields. Validate and save this draft once to upgrade it; the controls then appear here.</p>}
          <label className="field"><span>Arbitration</span>
            <select aria-label="noc arbitration" value={String(noc.arbitration ?? '')} onChange={e => setNoc(n => ({ ...n, arbitration: e.target.value || null }))}>
              <option value="">Compiler default (iSLIP)</option>
              <option value="islip">iSLIP</option>
              {/* The authored router proof covers iSLIP only; offering round robin as a
                  choice would promise execution the backend refuses. */}
              <option value="round_robin" disabled>Round robin (not executable)</option>
              {noc.arbitration && !['islip', 'round_robin'].includes(noc.arbitration) && <option value={noc.arbitration}>{noc.arbitration}</option>}
            </select>
            <small>Authored router execution currently proves iSLIP only; round robin is refused rather than substituted.</small>
          </label>
        </div>}
      </div>
    </div>

    {!tuning && <p className="probe-line">
      <Badge tone={derivedVc ? 'blue' : 'neutral'}>{derivedVc ? `${derivedVc} VC${derivedVc === 1 ? '' : 's'} derived` : 'VC count not derived yet'}</Badge>
      <span className="muted">VC count and deadlock rules are compiler-derived; recompile after changes.</span>
    </p>}

    {!tuning && selectedFamily && <p className="probe-line">
      <Badge tone={statusTone(selectedFamily.status)}>{selectedFamily.status}</Badge>
      {selectedFamily.status !== 'READY' && <span className="muted">Stopped at {selectedFamily.stopped_at ?? 'an undeclared stage'}. {selectedFamily.reason ?? ''}</span>}
    </p>}

    {isExplicit && <div className="section"><div className="section-heading"><h2>Explicit topology graph</h2></div>
      <div className="form-grid">
        {textRow('Graph name', graph.name, next => setGraph(g => ({ ...g, name: next })))}
        <label className="field"><span>Graph kind</span><select aria-label="explicit graph kind" value={graph.kind} onChange={e => setGraph(g => ({ ...g, kind: e.target.value }))}>{GRAPH_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></label>
        <label className="field"><span>Nodes</span><input aria-label="explicit graph nodes" value={graph.nodes} onChange={e => setGraph(g => ({ ...g, nodes: e.target.value }))} /></label>
        <label className="field"><span>Link bandwidth GB/s</span><input aria-label="explicit graph bandwidth" value={graph.bandwidth} onChange={e => setGraph(g => ({ ...g, bandwidth: e.target.value }))} /></label>
        <label className="field"><span>Link latency ns</span><input aria-label="explicit graph latency" value={graph.latency} onChange={e => setGraph(g => ({ ...g, latency: e.target.value }))} /></label>
      </div>
      <FabricCanvas nodes={canvasCount} links={canvasLinks} onToggleLink={canvasToggle} />
      <label className="field"><span>Links (src dst per line)</span><textarea aria-label="explicit graph links" className="code-preview" rows={6} spellCheck={false} value={graph.links} onChange={e => setGraph(g => ({ ...g, links: e.target.value }))} /></label>
    </div>}

    {familyProbe.phase === 'ready' && familyProbe.families.length > 0 && <details className="probe-table">
      <summary><strong>Backend topology families</strong> <span className="muted">· {familyProbe.families.length} probed by GET /api/v1/loom/capabilities</span></summary>
      <div className="table-scroll capped"><table><thead><tr><th>Family</th><th>Status</th><th>Stopped at</th><th>Probe reason</th></tr></thead><tbody>
        {familyProbe.families.map(row => <tr key={row.family}>
          <th className="mono">{row.family}</th>
          <td><Badge tone={statusTone(row.status)}>{row.status}</Badge></td>
          <td>{row.stopped_at ?? '—'}</td>
          <td className="probe-reason">{row.reason ?? '—'}</td>
        </tr>)}
      </tbody></table></div>
    </details>}

    {!tuning && <details open>
    <summary>Endpoint agents, address ranges & traffic dependencies</summary>
    <h3>Agents · {agents.reduce((n, a) => n + (a.count ?? 0), 0)}</h3>
    <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Clock domain</th><th>Power domain</th><th>Protocol</th><th>Actions</th></tr></thead><tbody>
      {agents.map((agent, index) => <tr key={`${agent.kind}-${index}`}>
        <th><select aria-label={`agent ${index + 1} kind`} value={agent.kind}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, kind: e.target.value } : a))}>
          {AGENT_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}
        </select></th>
        <td><input type="number" aria-label={`agent ${index + 1} count`} value={agent.count ?? 0}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, count: Number(e.target.value) } : a))} /></td>
        <td><input type="number" aria-label={`agent ${index + 1} width`} value={agent.data_width ?? ''}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, data_width: Number(e.target.value) } : a))} /></td>
        <td><input aria-label={`agent ${index + 1} clock domain`} placeholder="null" value={String(agent.clock_domain ?? '')}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, clock_domain: e.target.value.trim() ? e.target.value : null } : a))} /></td>
        <td><input aria-label={`agent ${index + 1} power domain`} placeholder="null" value={String(agent.power_domain ?? '')}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, power_domain: e.target.value.trim() ? e.target.value : null } : a))} /></td>
        <td>{agent.protocol ?? '—'}</td>
        <td><Button onClick={() => { invalidate(); setAgents(list => list.filter((_, i) => i !== index)); }}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar">
      <Button onClick={() => { invalidate(); setAgents(list => [...list, { kind: 'compute_tile', count: 1, data_width: physical.data_width ?? 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null }]); }}>Add agent</Button>
    </div>

    <h3>Address ranges · {ranges.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base (decimal or 0x hex)</th><th>Size (bytes)</th><th>Target agent index</th><th>Actions</th></tr></thead><tbody>
      {ranges.map((range, index) => <tr key={index}>
        <th><input aria-label={`address range ${index + 1} name`} value={range.name} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, name: e.target.value } : r))} /></th>
        <td><input aria-label={`address range ${index + 1} base`} value={range.base} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, base: e.target.value } : r))} /></td>
        <td><input aria-label={`address range ${index + 1} size`} value={range.size} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, size: e.target.value } : r))} /></td>
        <td><input aria-label={`address range ${index + 1} target`} value={range.target} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, target: e.target.value } : r))} /></td>
        <td><Button onClick={() => { invalidate(); setRanges(list => list.filter((_, i) => i !== index)); }}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => { invalidate(); setRanges(list => [...list, { name: '', base: '', size: '', target: '0' }]); }}>Add address range</Button></div>

    <h3>Traffic-class dependencies · {dependencies.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Source traffic class</th><th>Target traffic class</th><th>Kind</th><th>Actions</th></tr></thead><tbody>
      {dependencies.map((dependency, index) => <tr key={index}>
        <th><input aria-label={`dependency ${index + 1} source`} value={dependency.source} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, source: e.target.value } : d))} /></th>
        <td><input aria-label={`dependency ${index + 1} target`} value={dependency.target} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, target: e.target.value } : d))} /></td>
        <td><select aria-label={`dependency ${index + 1} kind`} value={dependency.kind} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, kind: e.target.value } : d))}>{DEP_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></td>
        <td><Button onClick={() => { invalidate(); setDependencies(list => list.filter((_, i) => i !== index)); }}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => { invalidate(); setDependencies(list => [...list, { source: '', target: '', kind: 'blocking' }]); }}>Add dependency</Button></div>
    </details>}
    </fieldset>
    {preview && <Notice tone="blue"><strong>Topology accepted</strong> by the gateway's canonicalizer.</Notice>}
    {tuning && <div className="draft-save-bar">
      <div className="draft-save-status">
        <Badge tone={ready ? 'green' : 'amber'}>{ready ? 'Revision compiled' : dirty ? 'Unsaved changes' : 'Needs compile'}</Badge>
        <Badge tone={derivedVc ? 'blue' : 'neutral'}>{derivedVc ? `${derivedVc} VC${derivedVc === 1 ? '' : 's'} derived` : 'VCs not derived'}</Badge>
        {selectedFamily && <Badge tone={statusTone(selectedFamily.status)}>{selectedFamily.status}</Badge>}
        <small>{ready ? 'Next can validate the compiled revision.' : canValidate ? 'Save the form, then compile it before final validation.' : 'This topology family is not authorable in the form.'}</small>
        {error && <span className="error-text">{error}</span>}
      </div>
      <div className="draft-save-actions">
        <Button primary={!ready} disabled={busy !== null || !canValidate || ready} onClick={saveAndCompile}>{busy === 'preview' ? 'Validating…' : busy === 'save' ? 'Saving…' : busy === 'compile' ? 'Compiling…' : 'Save & compile'}</Button>
        <Button primary={ready} disabled={!ready} onClick={onContinue}>Next · Final validation & RTL</Button>
      </div>
    </div>}
    {!embedded && error && <Notice tone="red">{error}</Notice>}
    {!tuning && <Properties rows={[[ 'Save', 'PUT /api/v1/projects/{id}/draft' ], ['Validate', 'POST /api/v1/projects/{id}/topology-preview' ]]} />}
  </div>;
}
