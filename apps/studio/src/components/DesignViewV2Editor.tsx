import { useMemo, useState, type ReactElement } from 'react';
import type {
  DesignEntry, DesignFinding, DesignSection, DesignViewV2,
} from '../api';
import { clone } from '../util';

/** Canonical field path -> location in the draft document.
 *
 * The BACKEND owns the field inventory, labels, exposure classes,
 * disclosure depths, findings and readiness (Gate 7 §51). Studio owns only
 * the mapping from a canonical path to an input. Nothing here classifies a
 * field or decides whether a value is valid.
 */
type Location =
  | { kind: 'scalar'; path: string[] }
  /** `rows` is the dotted path to the repeated child list. */
  | { kind: 'row'; rows: string; field: string; label?: string };

const LOCATIONS: Record<string, Location> = {
  'WorkloadV3.model_family': { kind: 'scalar', path: ['workload', 'model_family'] },
  'WorkloadV3.model_name': { kind: 'scalar', path: ['workload', 'model_name'] },
  'WorkloadV3.serving_mode': { kind: 'scalar', path: ['workload', 'serving_mode'] },
  'WorkloadV3.tp': { kind: 'scalar', path: ['workload', 'tp'] },
  'WorkloadV3.pp': { kind: 'scalar', path: ['workload', 'pp'] },
  'WorkloadV3.ep': { kind: 'scalar', path: ['workload', 'ep'] },
  'WorkloadV3.dp': { kind: 'scalar', path: ['workload', 'dp'] },
  'NocConfig.topology_family': { kind: 'scalar', path: ['noc_config', 'topology_family'] },
  'NocConfig.radix': { kind: 'scalar', path: ['noc_config', 'radix'] },
  'NocConfig.concentration': { kind: 'scalar', path: ['noc_config', 'concentration'] },
  'NocConfig.link_width': { kind: 'scalar', path: ['noc_config', 'link_width'] },
  'NocConfig.arbitration': { kind: 'scalar', path: ['noc_config', 'arbitration'] },
  'NocConfig.output_formats': { kind: 'scalar', path: ['noc_config', 'output_formats'] },
  'NocConfig.obfuscation_level': { kind: 'scalar', path: ['noc_config', 'obfuscation_level'] },
  'PhysicalContext.default_clock_freq_mhz': { kind: 'scalar', path: ['physical', 'clock_freq_mhz'] },
  'PhysicalContext.default_data_width': { kind: 'scalar', path: ['physical', 'data_width'] },
  'PhysicalContext.num_power_domains': { kind: 'scalar', path: ['physical', 'num_power_domains'] },
  'Agent.kind': { kind: 'row', rows: 'agents', field: 'kind' },
  'Agent.count': { kind: 'row', rows: 'agents', field: 'count' },
  'Agent.data_width': { kind: 'row', rows: 'agents', field: 'data_width' },
  'Agent.addr_width': { kind: 'row', rows: 'agents', field: 'addr_width' },
  'Agent.protocol': { kind: 'row', rows: 'agents', field: 'protocol' },
  'Agent.clock_domain': { kind: 'row', rows: 'agents', field: 'clock_domain' },
  'Agent.power_domain': { kind: 'row', rows: 'agents', field: 'power_domain' },
  'RequirementV3.qos_class': { kind: 'row', rows: 'requirements', field: 'qos_class' },
  'RequirementV3.traffic_class': { kind: 'row', rows: 'requirements', field: 'traffic_class' },
  'RequirementV3.latency_ceiling_cycles': { kind: 'row', rows: 'requirements', field: 'latency_ceiling_cycles' },
  'RequirementV3.binding': { kind: 'row', rows: 'requirements', field: 'binding' },
  'AddressRange.name': { kind: 'row', rows: 'address_map.ranges', field: 'name' },
  'AddressRange.base': { kind: 'row', rows: 'address_map.ranges', field: 'base' },
  'AddressRange.size': { kind: 'row', rows: 'address_map.ranges', field: 'size' },
  'AddressRange.target_agent_idx': { kind: 'row', rows: 'address_map.ranges', field: 'target_agent_idx' },
};

/** Workbench groups (Studio vNext §6). The backend owns sections; Studio
 * groups them into the authoring workflow. Mapping is by entry-field
 * prefix majority, so unknown backend sections still land somewhere
 * honest instead of disappearing. */
const WORKBENCH_GROUPS = ['system', 'workload', 'fabric', 'goals'] as const;
export type WorkbenchGroup = (typeof WORKBENCH_GROUPS)[number];

const GROUP_LABELS: Record<WorkbenchGroup, string> = {
  system: 'System',
  workload: 'Workload',
  fabric: 'Fabric',
  goals: 'Goals',
};

function sectionGroup(section: DesignSection): WorkbenchGroup {
  const counts: Record<WorkbenchGroup, number> = {
    system: 0, workload: 0, fabric: 0, goals: 0,
  };
  for (const entry of section.entries) {
    const f = entry.field;
    if (/^(Agent|PhysicalContext|AddressRange|AddressMap)\b/.test(f))
      counts.system += 1;
    else if (/^(WorkloadV3|CollectiveIntent|Dependency|WorkloadSourceRef)\b/.test(f))
      counts.workload += 1;
    else if (/^(NocConfig|NocControls|CompileRequestV4\.topology|CompileRequestV3\.explicit_topology|CompileIntent)\b/.test(f))
      counts.fabric += 1;
    else if (/^RequirementV3\b/.test(f))
      counts.goals += 1;
  }
  let best: WorkbenchGroup = 'system';
  for (const g of WORKBENCH_GROUPS) {
    if (counts[g] > counts[best]) best = g;
  }
  // Fall back to section id/title hints when entries say nothing.
  if (counts[best] === 0) {
    const hay = `${section.id} ${section.title}`.toLowerCase();
    if (/workload|parallel|operation|collective|dependenc/.test(hay))
      return 'workload';
    if (/fabric|topolog|noc|rout|resourc|arbitrat/.test(hay)) return 'fabric';
    if (/goal|requirement|objective|analysis/.test(hay)) return 'goals';
  }
  return best;
}

/** Owner domain -> workbench group for finding-remediation navigation. */
function groupForOwner(owner: string): WorkbenchGroup {
  const o = owner.toUpperCase();
  if (['WORKLOAD', 'PARALLELISM', 'COMMUNICATION'].includes(o))
    return 'workload';
  if (['FABRIC', 'ROUTER_RESOURCE'].includes(o)) return 'fabric';
  if (['REQUIREMENTS', 'DESIGN_SPACE'].includes(o)) return 'goals';
  return 'system';
}

/** Topology picker groups (Studio vNext §6 FABRIC). Values are exactly the
 * backend TopologyFamily enum — Studio never invents a family. Maturity
 * rows come from the staged registry vocabulary, not from execution. */
const TOPOLOGY_GROUPS: { title: string; options: string[] }[] = [
  { title: 'Qualified', options: ['mesh', 'concentrated_mesh', 'custom'] },
  { title: 'Canonical / bridge incomplete', options: ['torus'] },
  { title: 'Backend / reclamation', options: ['gec', 'fat_tree'] },
];

const TOPOLOGY_MATURITY: Record<string, string> = {
  mesh: 'Qualified — intent ✓ materialized ✓ verified ✓ projected ✓ executable ✓ qualified ✓',
  concentrated_mesh:
    'Qualified under the concentrated-mesh envelope — routing DOR-XY, seat capacity 4',
  custom:
    'Explicit topology — qualified where the canonical route + envelope hold',
  torus:
    'Canonical intent ✓ physical topology ✓ · routing proof pending · BookSim implements torus · historical measurement exists — compilation stops at ROUTING',
  gec:
    'Backend implements GEC mesh/express/MECS/hybrid · canonical materializer missing (MECS needs a shared-multidrop resource) · historical measurement exists — research',
  fat_tree:
    'Backend implements fat-tree · canonical materializer + route class missing · historical measurement exists — research',
};

const TOPOLOGY_STOP_STAGE: Record<string, string | null> = {
  mesh: null,
  concentrated_mesh: null,
  custom: null,
  torus: 'If selected, compilation stops at ROUTING: wraparound routing proof is pending.',
  gec: 'If selected, compilation stops at MATERIALIZATION: no canonical GEC materializer exists.',
  fat_tree:
    'If selected, compilation stops at MATERIALIZATION: no canonical fat-tree materializer exists.',
};

const SELECTS: Record<string, [string, string][]> = {
  'WorkloadV3.model_family': [
    ['dense_transformer', 'Dense transformer'],
    ['mixture_of_experts', 'Mixture of experts'],
    ['diffusion', 'Diffusion'], ['cnn', 'CNN'], ['custom', 'Custom'],
  ],
  'WorkloadV3.serving_mode': [
    ['prefill_heavy', 'Prefill heavy'], ['decode_heavy', 'Decode heavy'],
    ['mixed', 'Mixed'],
  ],
  'NocConfig.topology_family': [
    ['mesh', 'Mesh'], ['concentrated_mesh', 'Concentrated mesh'],
    ['custom', 'Custom explicit topology'],
    ['torus', 'Torus'], ['gec', 'GEC'], ['fat_tree', 'Fat tree'],
  ],
  // One canonical policy field — never a VC allocator + switch allocator.
  'NocConfig.arbitration': [
    ['islip', 'iSLIP'], ['round_robin', 'Round robin'],
  ],
  'RequirementV3.qos_class': [
    ['latency_critical', 'Latency critical'], ['bandwidth', 'Bandwidth'],
    ['best_effort', 'Best effort'],
  ],
};

function readScalar(doc: Record<string, unknown>, path: string[]): unknown {
  let node: unknown = doc;
  for (const key of path) {
    if (node === null || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function writeScalar(
  doc: Record<string, unknown>, path: string[], value: unknown,
): Record<string, unknown> {
  const next = clone(doc);
  let node = next;
  for (const key of path.slice(0, -1)) {
    const child = node[key];
    node[key] = child && typeof child === 'object' ? child : {};
    node = node[key] as Record<string, unknown>;
  }
  node[path[path.length - 1]] = value;
  return next;
}

function readRows(doc: Record<string, unknown>, path: string): unknown[] {
  const rows = readScalar(doc, path.split('.'));
  return Array.isArray(rows) ? rows : [];
}

function writeRows(
  doc: Record<string, unknown>, path: string[], rows: unknown[],
): Record<string, unknown> {
  return writeScalar(doc, path, rows);
}

const FINDING_GLYPH: Record<string, string> = {
  BLOCKING_ERROR: '!',
  DOWNSTREAM_LIMITATION: '⚠',
  INFORMATION: 'ⓘ',
  LEGACY_MIGRATION_NOTICE: '⚑',
};

const FINDING_LABEL: Record<string, string> = {
  BLOCKING_ERROR: 'BLOCKING ERROR',
  DOWNSTREAM_LIMITATION: 'DOWNSTREAM LIMITATION',
  INFORMATION: 'INFORMATION',
  LEGACY_MIGRATION_NOTICE: 'LEGACY / MIGRATION',
};

const READINESS_LABEL: Record<string, string> = {
  READY: '✓ READY TO REVIEW',
  INCOMPLETE: '! INCOMPLETE — a mandatory value is missing',
  INVALID: '! INVALID — the intent violates its contract',
  PREFLIGHT_BLOCKED: '! BLOCKED — a cross-domain join is infeasible',
  CAPABILITY_LIMITED_BUT_COMPILABLE:
    '⚠ VALID BUT DOWNSTREAM LIMITED — compilation is available',
};

function Finding({
  finding, onGoTo,
}: { finding: DesignFinding; onGoTo: (owner: string) => void }): ReactElement {
  return (
    <div className={`finding finding-${finding.class.toLowerCase()}`}>
      <div className="finding-head">
        <span className="finding-glyph" aria-hidden="true">
          {FINDING_GLYPH[finding.class]}
        </span>
        <strong>{FINDING_LABEL[finding.class]}</strong>
        <code className="muted">{finding.code}</code>
        <span className="muted">· {finding.owner_domain}</span>
      </div>
      <p className="finding-body">{finding.message}</p>
      {finding.affected && (
        <p className="muted finding-affected">
          affected <code>{finding.affected}</code>
        </p>
      )}
      {finding.remediation_owners.length > 0 && (
        <p className="finding-remedies">
          {finding.remediation_owners.map((owner) => (
            <button
              key={owner}
              className="btn btn-small"
              onClick={() => onGoTo(owner)}
            >
              {owner}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}

function EntryInput({
  entry, doc, onChange, readOnly,
}: {
  entry: DesignEntry;
  doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  readOnly: boolean;
}): ReactElement | null {
  const location = LOCATIONS[entry.field];
  if (!location) return null;

  if (location.kind === 'row') {
    // Repeated children are rendered as a table by the caller; a single
    // row-level input makes no sense here.
    return null;
  }

  const value = readScalar(doc, location.path);
  const options = SELECTS[entry.field];
  const set = (next: unknown): void =>
    onChange(writeScalar(doc, location.path, next));

  if (options) {
    return (
      <select
        value={String(value ?? '')}
        disabled={readOnly}
        onChange={(e) => set(e.target.value || null)}
      >
        <option value="">—</option>
        {options.map(([v, label]) => (
          <option key={v} value={v}>{label}</option>
        ))}
      </select>
    );
  }
  if (typeof value === 'boolean' || entry.field.endsWith('.binding')) {
    return (
      <input
        type="checkbox"
        checked={value === true}
        disabled={readOnly}
        onChange={(e) => set(e.target.checked)}
      />
    );
  }
  if (typeof value === 'number' || value === null || value === undefined) {
    return (
      <input
        type="number"
        value={value === null || value === undefined ? '' : String(value)}
        disabled={readOnly}
        onChange={(e) =>
          set(e.target.value === '' ? null : Number(e.target.value))}
      />
    );
  }
  return (
    <input
      value={String(value ?? '')}
      disabled={readOnly}
      onChange={(e) => set(e.target.value)}
    />
  );
}

/** Grouped topology picker with maturity rows (Studio vNext §6 FABRIC).
 *
 * Values are exactly the backend TopologyFamily enum. Nothing disappears:
 * bridge-incomplete and reclamation families stay selectable with an
 * honest stop-stage notice; the compiler — not Studio — refuses what it
 * cannot build, and its findings say where compilation stops. */
function TopologyPicker({
  value, onChange, readOnly,
}: {
  value: unknown;
  onChange: (next: unknown) => void;
  readOnly: boolean;
}): ReactElement {
  const current = typeof value === 'string' ? value : '';
  return (
    <div className="topology-picker">
      {TOPOLOGY_GROUPS.map((group) => (
        <fieldset key={group.title} className="topology-group">
          <legend>{group.title}</legend>
          {group.options.map((option) => (
            <label key={option} className="topology-option">
              <input
                type="radio"
                name="topology_family"
                value={option}
                checked={current === option}
                disabled={readOnly}
                onChange={() => onChange(option)}
              />
              <span className="topology-name">{option}</span>
              <span className="muted topology-maturity">
                {TOPOLOGY_MATURITY[option]}
              </span>
            </label>
          ))}
        </fieldset>
      ))}
      <p className="muted">
        Generated graphs enter as <code>custom</code> explicit topologies via
        candidate promotion (Synthesize → promote → compile).
      </p>
      {current && TOPOLOGY_STOP_STAGE[current] && (
        <p className="finding finding-downstream_limitation" role="note">
          <strong>Use experimentally.</strong> {TOPOLOGY_STOP_STAGE[current]}
        </p>
      )}
    </div>
  );
}

/** Derived parallelism preview: TP × PP × EP × DP rank count.
 * Read-only arithmetic over declared intent — never a backend claim. */
function ParallelismPreview({
  doc,
}: {
  doc: Record<string, unknown>;
}): ReactElement | null {
  const workload = (doc['workload'] ?? {}) as Record<string, unknown>;
  const dims = (['tp', 'pp', 'ep', 'dp'] as const).map((dim) => {
    const raw = workload[dim];
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
  });
  if (dims.every((d) => d === null)) return null;
  const known = dims.filter((d): d is number => d !== null);
  const ranks = known.reduce((a, b) => a * b, 1);
  return (
    <p className="derived-preview" title="DECLARED intent × DERIVED rank count">
      Parallelism TP{ dims[0] ?? '·'} · PP{dims[1] ?? '·'} · EP{dims[2] ?? '·'} · DP{dims[3] ?? '·'}
      {' '}→ <strong>{known.length === 4 ? `${ranks} ranks` : `≥ ${ranks} ranks (partial)`}</strong>{' '}
      <span className="muted">DERIVED preview</span>
    </p>
  );
}

/** Agent inventory summary + placement preview (automatic unless pinned). */
function PlacementPreview({
  doc,
}: {
  doc: Record<string, unknown>;
}): ReactElement | null {
  const agents = doc['agents'];
  if (!Array.isArray(agents) || agents.length === 0) return null;
  const parts = agents.map((agent) => {
    const row = (agent ?? {}) as Record<string, unknown>;
    return `${String(row['count'] ?? '?')}× ${String(row['kind'] ?? 'agent')}`;
  });
  return (
    <p className="derived-preview">
      Placement: automatic rank→endpoint mapping over {parts.join(', ')}{' '}
      <span className="muted">DERIVED at compile · explicit pinning is advanced</span>
    </p>
  );
}

/** Empty-memory honest state: no map means identity transform. */
function MemoryEmptyState({
  doc, hasAddressEntries,
}: {
  doc: Record<string, unknown>;
  hasAddressEntries: boolean;
}): ReactElement | null {
  if (!hasAddressEntries) return null;
  const map = (doc['address_map'] ?? {}) as Record<string, unknown>;
  const ranges = map['ranges'];
  if (Array.isArray(ranges) && ranges.length > 0) return null;
  return (
    <p className="derived-preview" role="note">
      <strong>No explicit memory-address map.</strong> Identity transform
      applies — every address decodes to its declaring agent.{' '}
      <span className="muted">HBM inventory, once declared, appears here.</span>
    </p>
  );
}

/** Class → VC treatment is compiler-derived; preview the law, not values. */
function ClassVcPreview({
  show,
}: {
  show: boolean;
}): ReactElement | null {
  if (!show) return null;
  return (
    <p className="derived-preview">
      Communication classes map to VC subsets at compile (class-aware
      derivation). Inspect the derived assignment under Compile → Resources.{' '}
      <span className="muted">DERIVED — not editable here</span>
    </p>
  );
}

/** Advanced Fabric: routing & resources inspector note (Studio vNext §6).
 *
 * Routing policy is compiler-derived; Studio lists what the capability
 * stages allow and never exposes a raw BookSim routing_function string. */
function RoutingResourcesNote({
  show,
}: {
  show: boolean;
}): ReactElement | null {
  if (!show) return null;
  return (
    <section className="card" aria-label="Routing and resources (advanced fabric)">
      <h4>Routing &amp; resources — advanced Fabric</h4>
      <ul className="maturity-list">
        <li><strong>Deterministic</strong> — DOR-XY (mesh), AnyNet minimum-hop (explicit) · AVAILABLE</li>
        <li><strong>Adaptive / Valiant / UGAL / ROMM / Chaos / planar / GEC-specific</strong> — backend research, no canonical projection · RESEARCH</li>
      </ul>
      <p className="muted">
        VC count, VC map, route table, escape VCs and turn restrictions are
        compiler-derived correctness state: inspectable under Compile →
        Routing / Resources, never edited here. Arbitration policies apply
        where the backend profile qualifies them.
      </p>
      <p className="muted">
        Hardware multicast: RESEARCH / historically executable — conceptual
        controls appear only under an experimental envelope. Multiplane:
        RESEARCH — the simultaneous plane contract is not yet canonical;
        independent per-plane runs are never one multiplane fabric.
      </p>
    </section>
  );
}

/** Physical assumptions footer: clocks + CDC status. */
function PhysicalNote({ show }: { show: boolean }): ReactElement | null {
  if (!show) return null;
  return (
    <p className="derived-preview">
      Clocks declared here are design intent, not backend execution clocks.
      Multi-clock / CDC fabric execution is not established — CDC research
      lives under Implementation Lab.{' '}
      <span className="muted">Link latency/bandwidth attributes are physical assumptions.</span>
    </p>
  );
}

/** Legacy migration drawer: imported fields live here, not beside live controls. */
function LegacyDrawer({
  findings,
}: {
  findings: DesignFinding[];
}): ReactElement | null {
  const legacy = findings.filter(
    (f) => f.class === 'LEGACY_MIGRATION_NOTICE');
  if (legacy.length === 0) return null;
  return (
    <details className="legacy-drawer">
      <summary>
        Imported legacy fields ({legacy.length}) — compatibility only
      </summary>
      <ul>
        {legacy.map((finding, index) => (
          <li key={index}>
            <code>{finding.code}</code> — {finding.message}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Analysis goals preconfiguration (Studio vNext §6 GOALS). */
function AnalysisGoals({
  projectId,
}: {
  projectId?: string;
}): ReactElement {
  const goals = [
    'Network completion',
    'System makespan',
    'Communication exposure',
    'Per-rank completion',
    'DRAM timing',
    'Request latency (model)',
    'Critical path (model)',
    'Resource utilization (model)',
    'Serving TTFT / completion',
  ];
  return (
    <section className="card" aria-label="Analysis goals">
      <h4>Analysis goals</h4>
      <p className="muted">
        Selecting goals preconfigures Evaluate and Optimize. Model goals are
        MODELLED and uncalibrated — never measured.
      </p>
      <ul className="goal-list">
        {goals.map((goal) => <li key={goal}>{goal}</li>)}
      </ul>
      {projectId && (
        <p>
          <a className="btn btn-small" href={`#/projects/${projectId}/simulate`}>
            Open Evaluate
          </a>{' '}
          <a className="btn btn-small" href={`#/projects/${projectId}/optimize`}>
            Open Optimize
          </a>
        </p>
      )}
    </section>
  );
}

function RowTable({
  section, doc, onChange, readOnly,
}: {
  section: DesignSection;
  doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  readOnly: boolean;
}): ReactElement | null {
  const rowEntries = section.entries.filter(
    (e) => LOCATIONS[e.field]?.kind === 'row');
  if (rowEntries.length === 0) return null;

  const groups = new Map<string, DesignEntry[]>();
  for (const entry of rowEntries) {
    const loc = LOCATIONS[entry.field] as Extract<Location, { kind: 'row' }>;
    const list = groups.get(loc.rows) ?? [];
    list.push(entry);
    groups.set(loc.rows, list);
  }

  return (
    <>
      {[...groups.entries()].map(([rowsPath, entries]) => {
        const rows = readRows(doc, rowsPath);
        return (
          <table className="tbl" key={rowsPath}>
            <thead>
              <tr>
                {entries.map((e) => <th key={e.field}>{e.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {entries.map((entry) => {
                    const loc = LOCATIONS[entry.field] as
                      Extract<Location, { kind: 'row' }>;
                    const cell = (row as Record<string, unknown>)?.[loc.field];
                    return (
                      <td key={entry.field} className="num">
                        <input
                          value={cell === null || cell === undefined
                            ? '' : String(cell)}
                          disabled={readOnly}
                          onChange={(e) => {
                            const nextRows = clone(rows);
                            const raw = e.target.value;
                            const numeric = loc.field !== 'kind'
                              && loc.field !== 'name'
                              && loc.field !== 'qos_class'
                              && loc.field !== 'traffic_class'
                              && loc.field !== 'protocol'
                              && loc.field !== 'clock_domain'
                              && loc.field !== 'power_domain';
                            (nextRows[index] as Record<string, unknown>)[loc.field] =
                              raw === '' ? null
                                : numeric ? Number(raw) : raw;
                            onChange(writeRows(doc, rowsPath.split('.'), nextRows));
                          }}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
    </>
  );
}

/**
 * The one canonical Design editor (Gate 6 §1, Gate 8 §8).
 *
 * Structure, labels, exposure classes, disclosure depths, readiness,
 * findings and capability consequences all come from the backend
 * DesignViewV2 projection. Progressive disclosure is presentation-only:
 * expanding or collapsing an Advanced area changes no value and cannot
 * make a Review stale.
 */
export default function DesignViewV2Editor({
  view, doc, onDocChange, onGoToSection, readOnly = false,
  sectionId, onSectionChange, projectId,
}: {
  view: DesignViewV2;
  doc: Record<string, unknown>;
  onDocChange: (next: Record<string, unknown>) => void;
  onGoToSection: (owner: string) => void;
  /** Review presents canonical completeness; authoring is editable. */
  readOnly?: boolean;
  sectionId: string;
  onSectionChange: (id: string) => void;
  /** Optional: enables Analysis-goals Evaluate/Optimize shortcuts. */
  projectId?: string;
}): ReactElement {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const section = useMemo(
    () => view.sections.find((s) => s.id === sectionId) ?? view.sections[0],
    [view.sections, sectionId]);

  const primary = section?.entries.filter(
    (e) => e.disclosure_depth === 'GUIDED') ?? [];
  const advanced = section?.entries.filter(
    (e) => e.disclosure_depth === 'EXPERT') ?? [];
  const advancedActive = advanced.filter((e) => e.active).length;
  const isExpanded = expanded[section?.id ?? ''] ?? readOnly;
  const group = section ? sectionGroup(section) : 'system';

  const fields = new Set((section?.entries ?? []).map((e) => e.field));
  const hasParallelism = ['WorkloadV3.tp', 'WorkloadV3.pp', 'WorkloadV3.ep', 'WorkloadV3.dp']
    .some((f) => fields.has(f));
  const hasAgents = [...fields].some((f) => f.startsWith('Agent.'));
  const hasAddress = [...fields].some((f) => f.startsWith('AddressRange.'));
  const hasClass = [...fields].some((f) => f.includes('traffic_class'));
  const hasArbitration = fields.has('NocConfig.arbitration');
  const hasPhysical = [...fields].some((f) => f.startsWith('PhysicalContext.'));
  const hasTopology = fields.has('NocConfig.topology_family');
  const isGoals = group === 'goals';

  const renderEntry = (entry: (typeof primary)[number]): ReactElement => {
    if (entry.field === 'NocConfig.topology_family') {
      const current = readScalar(doc, ['noc_config', 'topology_family']);
      return (
        <div key={entry.field} className="field field-topology">
          <span className="field-label">{entry.label}</span>
          <TopologyPicker
            value={current}
            onChange={(next) =>
              onChangeDoc(writeScalar(doc, ['noc_config', 'topology_family'], next))}
            readOnly={readOnly}
          />
        </div>
      );
    }
    return (
      <label key={entry.field} className="field">
        <span className="field-label">
          {entry.label}
          {entry.source === 'RECOMMENDATION' && (
            <span className="field-hint"> ◆ recommended</span>
          )}
        </span>
        <EntryInput entry={entry} doc={doc}
                    onChange={onChangeDoc} readOnly={readOnly} />
        <span className="field-owner muted">
          {entry.ownership.domain}
          {entry.ownership.scientific_name
            ? ` · ${entry.ownership.scientific_name}` : ''}
        </span>
      </label>
    );
  };
  const onChangeDoc = (next: Record<string, unknown>): void => {
    onDocChange(next);
  };

  return (
    <div className="design-v2" data-workbench-group={group}>
      <p className="muted workbench-group-note" aria-label="Workbench group">
        {GROUP_LABELS[group]} — {
          group === 'system' ? 'agents, placement, memory and physical assumptions'
          : group === 'workload' ? 'template, parallelism, operations, classes and dependencies'
          : group === 'fabric' ? 'topology, geometry, links and advanced routing/resources'
          : 'requirements and analysis goals'}
      </p>
      <nav className="section-nav" aria-label="Design sections">
        {view.sections.map((s) => (
          <button
            key={s.id}
            className={`section-nav-item${s.id === section?.id ? ' active' : ''}`}
            aria-current={s.id === section?.id ? 'true' : undefined}
            onClick={() => onSectionChange(s.id)}
            title={`Workbench group: ${GROUP_LABELS[sectionGroup(s)]}`}
          >
            <span className="section-nav-title">{s.title}</span>
            {s.blocking_count > 0 && (
              <span className="section-nav-count bad">
                <span aria-hidden="true">!</span>{s.blocking_count}
              </span>
            )}
            {s.limitation_count > 0 && (
              <span className="section-nav-count warn">
                <span aria-hidden="true">⚠</span>{s.limitation_count}
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="design-v2-main">
        <h3>{section?.title}</h3>

        {hasParallelism && <ParallelismPreview doc={doc} />}
        {hasAgents && <PlacementPreview doc={doc} />}

        <div className="form-grid">
          {primary.map((entry) => renderEntry(entry))}
        </div>

        <RowTable section={section!} doc={doc} onChange={onDocChange}
                  readOnly={readOnly} />

        <MemoryEmptyState doc={doc} hasAddressEntries={hasAddress} />
        <ClassVcPreview show={hasClass || hasTopology} />
        <PhysicalNote show={hasPhysical} />
        {hasTopology && !readOnly && (
          <p className="muted">
            Synthesized graphs arrive via Synthesize → candidate promotion as{' '}
            <code>custom</code> explicit topologies.
          </p>
        )}

        {advanced.length > 0 && (
          <div className="advanced">
            <button
              className="advanced-toggle"
              aria-expanded={isExpanded}
              onClick={() => setExpanded((prev) => ({
                ...prev, [section!.id]: !isExpanded,
              }))}
            >
              <span aria-hidden="true">{isExpanded ? '▾' : '▸'}</span>{' '}
              Advanced — {advancedActive > 0
                ? `${advancedActive} value${advancedActive === 1 ? '' : 's'} active`
                : 'defaults'}
            </button>
            {isExpanded && (
              <div className="form-grid advanced-body">
                {advanced.map((entry) => (
                  <label key={entry.field} className="field">
                    <span className="field-label">{entry.label}</span>
                    <EntryInput entry={entry} doc={doc}
                                onChange={onDocChange} readOnly={readOnly} />
                    <span className="field-owner muted">
                      {entry.ownership.domain}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        <RoutingResourcesNote show={hasArbitration} />

        {isGoals && <AnalysisGoals projectId={projectId} />}

        <div className="findings">
          {view.validation_findings.map((finding, index) => (
            <Finding key={index} finding={finding} onGoTo={onGoToSection} />
          ))}
        </div>
        <LegacyDrawer findings={view.validation_findings} />
      </div>
    </div>
  );
}

export {
  READINESS_LABEL, FINDING_GLYPH, FINDING_LABEL,
  WORKBENCH_GROUPS, GROUP_LABELS, sectionGroup, groupForOwner,
};
