import { useMemo, useState, type ReactElement } from 'react';
import type {
  DesignEntry, DesignFinding, DesignSection, DesignViewV2,
} from '../api';
import { clone } from '../util';
import { Prov } from './badges';

type Location =
  | { kind: 'scalar'; path: string[] }
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
  if (counts[best] === 0) {
    const hay = `${section.id} ${section.title}`.toLowerCase();
    if (/workload|parallel|operation|collective|dependenc/.test(hay))
      return 'workload';
    if (/fabric|topolog|noc|rout|resourc|arbitrat/.test(hay)) return 'fabric';
    if (/goal|requirement|objective|analysis/.test(hay)) return 'goals';
  }
  return best;
}

function groupForOwner(owner: string): WorkbenchGroup {
  const o = owner.toUpperCase();
  if (['WORKLOAD', 'PARALLELISM', 'COMMUNICATION'].includes(o))
    return 'workload';
  if (['FABRIC', 'ROUTER_RESOURCE'].includes(o)) return 'fabric';
  if (['REQUIREMENTS', 'DESIGN_SPACE'].includes(o)) return 'goals';
  return 'system';
}

const TOPOLOGY_GROUPS: { title: string; options: string[] }[] = [
  { title: 'Qualified', options: ['mesh', 'concentrated_mesh', 'custom'] },
  { title: 'Canonical / bridge incomplete', options: ['torus'] },
  { title: 'Backend / reclamation', options: ['gec', 'fat_tree'] },
];

const TOPOLOGY_NAME: Record<string, string> = {
  mesh: 'Mesh',
  concentrated_mesh: 'Concentrated mesh',
  custom: 'Custom',
  torus: 'Torus',
  gec: 'GEC',
  fat_tree: 'Fat tree',
};

const TOPOLOGY_MATURITY: Record<string, string> = {
  mesh: 'Qualified — intent ✓ materialized ✓ verified ✓ projected ✓ executable ✓ qualified ✓',
  concentrated_mesh:
    'Qualified under the concentrated-mesh envelope — routing DOR-XY, seat capacity 4',
  custom:
    'Explicit topology — qualified where the canonical route + envelope hold',
  torus:
    'Canonical intent ✓ physical topology ✓ · wraparound-minimal DOR route exists · deadlock-proof method pending · BookSim implements torus · historical measurement exists — compilation stops at ROUTING',
  gec:
    'Backend implements GEC mesh/express/MECS/hybrid · GEC-Express is canonically materializable (pure point-to-point) but the aggregate gec declaration still stops at MATERIALIZATION · MECS needs a shared-multidrop resource, never flattened · historical measurement exists — research',
  fat_tree:
    'Backend implements fat-tree · canonical materializer + route class missing · historical measurement exists — research',
};

const TOPOLOGY_NON_DECLARABLE_NOTE =
  'FlatFly (typed-intent authorable), Dragonfly, QTree and Tree4 are BookSim backend '
  + 'implementations, not declarable NocConfig values — see the Capabilities explorer.';

const TOPOLOGY_STOP_STAGE: Record<string, string | null> = {
  mesh: null,
  concentrated_mesh: null,
  custom: null,
  torus: 'If selected, compilation stops at ROUTING: wraparound routing proof is pending.',
  gec: 'If selected, compilation stops at MATERIALIZATION: the aggregate gec declaration carries no materializer (GEC-Express graphs can enter as custom explicit topologies via candidate promotion).',
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
  'NocConfig.arbitration': [
    ['islip', 'iSLIP'], ['round_robin', 'Round robin'],
  ],
  'RequirementV3.qos_class': [
    ['latency_critical', 'Latency critical'], ['bandwidth', 'Bandwidth'],
    ['best_effort', 'Best effort'],
  ],
};

const FIELD_LABELS: Record<string, string> = {
  'Agent.kind': 'Kind',
  'Agent.count': 'Count',
  'Agent.data_width': 'Data bits',
  'Agent.addr_width': 'Addr bits',
  'Agent.protocol': 'Protocol',
  'Agent.clock_domain': 'Clock domain',
  'Agent.power_domain': 'Power domain',
  'RequirementV3.qos_class': 'QoS class',
  'RequirementV3.traffic_class': 'Traffic class',
  'RequirementV3.latency_ceiling_cycles': 'Latency ceiling (cycles)',
  'RequirementV3.binding': 'Binding',
  'RequirementV3.applicability': 'Applies to',
  'CollectiveIntent.kind': 'Kind',
  'CollectiveIntent.dimension': 'Dimension',
  'CollectiveIntent.payload_bytes': 'Payload (bytes)',
  'CollectiveIntent.traffic_class': 'Traffic class',
  'CollectiveIntent.source_rank': 'Source rank',
  'WorkloadV3.model_family': 'Model family',
  'WorkloadV3.model_name': 'Model',
  'WorkloadV3.serving_mode': 'Mode',
  'WorkloadV3.tp': 'TP',
  'WorkloadV3.pp': 'PP',
  'WorkloadV3.ep': 'EP',
  'WorkloadV3.dp': 'DP',
  'WorkloadV3.collectives': 'Collectives',
  'NocConfig.topology_family': 'Topology',
  'NocConfig.radix': 'Grid side',
  'NocConfig.concentration': 'Concentration',
  'NocConfig.link_width': 'Link width (bits)',
  'NocConfig.arbitration': 'Arbitration',
  'NocConfig.output_formats': 'Output formats',
  'NocConfig.obfuscation_level': 'Obfuscation',
  'NocControls.link_width': 'Link width (bits)',
  'NocControls.arbitration': 'Arbitration policy',
  'NocControls.mcast_groups': 'Multicast groups',
  'NocControls.mcast_setup_cycles': 'Multicast setup (cycles)',
  'NocControls.rcu_enabled': 'RCU',
  'NocControls.obfuscation_level': 'Obfuscation',
  'NocControls.output_formats': 'Output formats',
  'PhysicalContext.default_clock_freq_mhz': 'Clock (MHz)',
  'PhysicalContext.default_data_width': 'Data width (bits)',
  'PhysicalContext.num_power_domains': 'Power domains',
  'AddressRange.name': 'Name',
  'AddressRange.base': 'Base',
  'AddressRange.size': 'Size',
  'AddressRange.target_agent_idx': 'Target agent',
  'Dependency.kind': 'Kind',
  'Dependency.source': 'Source',
  'Dependency.target': 'Target',
  'DependencyGraph.dependencies': 'Dependencies',
  'CompileRequestV4.topology': 'Topology override',
  'CompileRequestV3.explicit_topology': 'Explicit topology',
};

function humanLabel(field: string, backendLabel: string): string {
  const mapped = FIELD_LABELS[field];
  if (mapped) return mapped;
  if (backendLabel && backendLabel !== field && !backendLabel.includes('.')) {
    return backendLabel;
  }
  const leaf = field.includes('.') ? field.split('.').pop() as string : field;
  return leaf
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

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
              <span className="topology-name">{TOPOLOGY_NAME[option] ?? option}</span>
              <TopologyStatus option={option} />
            </label>
          ))}
        </fieldset>
      ))}
      {current && (
        <details className="subtle">
          <summary>Capability details — {TOPOLOGY_NAME[current] ?? current}</summary>
          <p className="muted">{TOPOLOGY_MATURITY[current]}</p>
          <p className="muted">{TOPOLOGY_NON_DECLARABLE_NOTE}</p>
        </details>
      )}
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

function TopologyStatus({ option }: { option: string }): ReactElement {
  if (['mesh', 'concentrated_mesh', 'custom'].includes(option)) {
    return <span className="status status-ok">Qualified</span>;
  }
  if (option === 'torus') {
    return <span className="status status-warn">Experimental</span>;
  }
  return <span className="status status-muted">Research</span>;
}

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

function PlacementPreview({
  doc,
}: {
  doc: Record<string, unknown>;
}): ReactElement | null {
  const agents = doc['agents'];
  if (!Array.isArray(agents) || agents.length === 0) return null;
  const complete = agents.filter((agent) => {
    const row = (agent ?? {}) as Record<string, unknown>;
    return row['kind'] != null && row['kind'] !== ''
      && typeof row['count'] === 'number';
  });
  const incomplete = agents.length - complete.length;
  const parts = complete.map((agent) => {
    const row = (agent ?? {}) as Record<string, unknown>;
    return `${String(row['count'] ?? '?')}× ${String(row['kind'] ?? 'agent')}`;
  });
  return (
    <p className="derived-preview">
      Placement: automatic rank→endpoint mapping
      {parts.length > 0 ? ` over ${parts.join(', ')}` : ''}
      {incomplete > 0 ? ` · ${incomplete} row${incomplete === 1 ? '' : 's'} awaiting kind and count` : ''}{' '}
      <span className="muted">derived at compile · explicit pinning is advanced</span>
    </p>
  );
}

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

function ClassVcPreview({
  show,
}: {
  show: boolean;
}): ReactElement | null {
  if (!show) return null;
  return (
    <p className="derived-preview">
      Communication classes map to VC subsets at compile (class-aware
      derivation). Inspect the derived assignment under Compile → Resources.
    </p>
  );
}

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
    <section className="card" aria-label="Analyses available downstream">
      <h4>Analyses available downstream</h4>
      <p className="muted">
        Evaluate and Optimize answer these questions for a compiled
        revision. Model goals are MODELLED and uncalibrated — never
        measured.
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

function EmptySection({
  sectionId, doc, onChange, readOnly,
}: {
  sectionId: string;
  doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  readOnly: boolean;
}): ReactElement {
  if (sectionId === 'memory_addressing') {
    const ranges = readRows(doc, 'address_map.ranges');
    const setRanges = (next: unknown[]): void => {
      onChange(writeRows(doc, ['address_map', 'ranges'], next));
    };
    return (
      <div>
        {ranges.length === 0 ? (
          <p className="muted">
            No explicit address map — identity mapping applies: every
            address decodes to its declaring agent.
          </p>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th><th>Base</th><th>Size (bytes)</th><th>Target agent</th>
                {!readOnly && <th aria-label="row actions"></th>}
              </tr>
            </thead>
            <tbody>
              {ranges.map((row, index) => {
                const r = (row ?? {}) as Record<string, unknown>;
                const set = (field: string, value: unknown): void => {
                  const next = clone(ranges);
                  (next[index] as Record<string, unknown>)[field] = value;
                  setRanges(next);
                };
                const numCell = (field: string): ReactElement => (
                  <td key={field} className="num">
                    <input
                      value={r[field] === null || r[field] === undefined ? '' : String(r[field])}
                      disabled={readOnly}
                      aria-label={field}
                      onChange={(e) => {
                        const raw = e.target.value;
                        set(field, raw === '' ? null : Number(raw));
                      }}
                    />
                  </td>
                );
                return (
                  <tr key={index}>
                    <td>
                      <input
                        value={r['name'] === null || r['name'] === undefined ? '' : String(r['name'])}
                        disabled={readOnly}
                        aria-label="Range name"
                        onChange={(e) => set('name', e.target.value)}
                      />
                    </td>
                    {numCell('base')}
                    {numCell('size')}
                    {numCell('target_agent_idx')}
                    {!readOnly && (
                      <td>
                        <button
                          className="btn btn-small btn-danger"
                          aria-label={`Remove range ${index + 1}`}
                          onClick={() => setRanges(ranges.filter((_, i) => i !== index))}
                        >
                          ✕
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {!readOnly && (
          <button
            className="btn btn-small"
            onClick={() => setRanges([...ranges, newAddressRange(ranges)])}
          >
            Add range
          </button>
        )}
      </div>
    );
  }
  return (
    <p className="muted">No editable fields in this section.</p>
  );
}

function WorkloadSwitcher({
  projectId,
}: {
  projectId?: string;
}): ReactElement | null {
  if (!projectId) return null;
  return (
    <p className="muted">
      Catalog workload —{' '}
      <a className="link" href={`/projects/${projectId}/workload`}>
        choose a different workload
      </a>{' '}
      (the revision stays immutable).
    </p>
  );
}

function agentRows(doc: Record<string, unknown>): Record<string, unknown>[] {
  const agents = doc['agents'];
  if (!Array.isArray(agents)) return [];
  return agents.map((a) => (a ?? {}) as Record<string, unknown>);
}

function AgentSummary({
  doc,
}: {
  doc: Record<string, unknown>;
}): ReactElement | null {
  const rows = agentRows(doc).filter(
    (r) => r['kind'] != null && r['kind'] !== ''
      && typeof r['count'] === 'number',
  );
  if (rows.length === 0) return null;
  const line = (match: RegExp): string | null => {
    const found = rows.filter((r) => match.test(String(r['kind'] ?? '')));
    if (found.length === 0) return null;
    const total = found.reduce(
      (a, r) => a + (typeof r['count'] === 'number' ? r['count'] as number : 0), 0);
    const kinds = [...new Set(found.map((r) => String(r['kind'])))].join(', ');
    return `${total} × ${kinds}`;
  };
  const compute = line(/compute/i);
  const memory = line(/hbm|memory/i);
  const first = rows[0];
  const iface = first['protocol'] != null || first['data_width'] != null
    ? [first['protocol'], first['data_width'] != null ? `${String(first['data_width'])}-bit data` : null,
      first['addr_width'] != null ? `${String(first['addr_width'])}-bit address` : null]
      .filter((v) => v != null).join(' · ')
    : null;
  return (
    <div className="agent-summary">
      <p className="muted"><Prov kind="DERIVED" /> read from the draft — edited in the table below, never here.</p>
      {compute && <div className="kv"><span>Compute</span><span>{compute}</span></div>}
      {memory && <div className="kv"><span>Memory</span><span>{memory}</span></div>}
      {iface && <div className="kv"><span>Interface</span><span>{iface}</span></div>}
      <PlacementPreview doc={doc} />
    </div>
  );
}

function CommunicationSummary({
  doc,
}: {
  doc: Record<string, unknown>;
}): ReactElement | null {
  const workload = (doc['workload'] ?? {}) as Record<string, unknown>;
  const collectives = workload['collectives'];
  if (!Array.isArray(collectives) || collectives.length === 0) return null;
  return (
    <div className="agent-summary">
      <div className="kv"><span>Phases</span>
        <span>{collectives.length} communication phase{collectives.length === 1 ? '' : 's'}</span>
      </div>
      {collectives.map((c, i) => {
        const row = (c ?? {}) as Record<string, unknown>;
        const kindRaw = String(row['kind'] ?? 'collective');
        const kind = kindRaw.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
        const bits = [
          row['dimension'] != null ? String(row['dimension']) : null,
          row['payload_bytes'] != null ? `${String(row['payload_bytes'])} bytes` : null,
          row['traffic_class'] != null ? String(row['traffic_class']) : null,
        ].filter((v) => v != null);
        return (
          <div className="kv" key={i}>
            <span>{kind}</span>
            <span className="muted">{bits.join(' · ') || '—'}</span>
          </div>
        );
      })}
      <div className="kv"><span>Traffic isolation</span><span><Prov kind="DERIVED" /> compiler derived</span></div>
      <div className="kv"><span>VC assignment</span><span><Prov kind="DERIVED" /> compiler derived</span></div>
    </div>
  );
}

const METADATA_COLS: Record<string, string[]> = {
  'agents': ['data_width', 'protocol'],
};

const ADVANCED_COLS: Record<string, string[]> = {
  'agents': ['clock_domain', 'power_domain'],
};

const EMPTY_TABLE_STATE: Record<string, { title: string; body: string; add: string }> = {
  'agents': {
    title: 'No agents declared',
    body: 'The compiler has no hardware to map — nothing will be placed.',
    add: 'Add agent',
  },
  'requirements': {
    title: 'No explicit goals',
    body: 'Defaults apply.',
    add: 'Add goal',
  },
  'address_map.ranges': {
    title: 'Default flat address space',
    body: 'No explicit regions configured.',
    add: 'Add address region',
  },
};
const ROW_DEFAULTS: Record<string, Record<string, unknown>> = {  'agents': {
    kind: 'compute_tile', count: 1, data_width: 256, addr_width: 64,
    protocol: 'AXI', clock_domain: null, power_domain: null,
  },
  'requirements': {
    qos_class: 'best_effort', traffic_class: null,
    latency_ceiling_cycles: null, binding: false,
  },
};

function newAddressRange(existing: unknown[]): Record<string, unknown> {
  const names = new Set(existing.map(
    (r) => String((r as Record<string, unknown>)?.['name'] ?? '')));
  let i = existing.length;
  while (names.has(`region-${i}`)) i += 1;
  return { name: `region-${i}`, base: 0, size: 4096, target_agent_idx: 0 };
}

function canAddRows(rowsPath: string): boolean {
  return rowsPath === 'address_map.ranges' || ROW_DEFAULTS[rowsPath] !== undefined;
}

function blankRow(rowsPath: string, rows: unknown[]): Record<string, unknown> {
  return rowsPath === 'address_map.ranges'
    ? newAddressRange(rows)
    : { ...(ROW_DEFAULTS[rowsPath] ?? {}) };
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
        const metaFields = METADATA_COLS[rowsPath] ?? [];
        const advancedFields = ADVANCED_COLS[rowsPath] ?? [];
        const shown = entries.filter((e) => {
          const loc = LOCATIONS[e.field] as Extract<Location, { kind: 'row' }>;
          return !metaFields.includes(loc.field) && !advancedFields.includes(loc.field);
        });
        const meta = entries.filter((e) => {
          const loc = LOCATIONS[e.field] as Extract<Location, { kind: 'row' }>;
          return metaFields.includes(loc.field);
        });
        const advancedCols = entries.filter((e) => {
          const loc = LOCATIONS[e.field] as Extract<Location, { kind: 'row' }>;
          return advancedFields.includes(loc.field);
        });
        const renderCell = (entry: DesignEntry, row: unknown, index: number): ReactElement => {
          const loc = LOCATIONS[entry.field] as
            Extract<Location, { kind: 'row' }>;
          const cell = (row as Record<string, unknown>)?.[loc.field];
          if (typeof cell === 'boolean') {
            return (
              <td key={entry.field}>
                <input
                  type="checkbox"
                  checked={cell}
                  disabled={readOnly}
                  aria-label={humanLabel(entry.field, entry.label)}
                  onChange={(e) => {
                    const nextRows = clone(rows);
                    (nextRows[index] as Record<string, unknown>)[loc.field] =
                      e.target.checked;
                    onChange(writeRows(doc, rowsPath.split('.'), nextRows));
                  }}
                />
              </td>
            );
          }
          return (
            <td key={entry.field} className="num">
              <input
                value={cell === null || cell === undefined
                  ? '' : String(cell)}
                disabled={readOnly}
                aria-label={humanLabel(entry.field, entry.label)}
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
        };
        const addRow = (): void => {
          onChange(writeRows(
            doc, rowsPath.split('.'),
            [...rows, blankRow(rowsPath, rows)],
          ));
        };
        const removeRow = (index: number): void => {
          onChange(writeRows(
            doc, rowsPath.split('.'),
            rows.filter((_, i) => i !== index),
          ));
        };
        const emptyState = EMPTY_TABLE_STATE[rowsPath] ?? {
          title: 'No rows yet', body: '', add: 'Add row',
        };
        if (rows.length === 0) {
          return (
            <div key={rowsPath} className="empty-state">
              <strong>{emptyState.title}</strong>
              {emptyState.body && <p className="muted">{emptyState.body}</p>}
              {!readOnly && canAddRows(rowsPath) && (
                <button className="btn btn-small" onClick={addRow}>
                  {emptyState.add}
                </button>
              )}
            </div>
          );
        }
        return (
          <div key={rowsPath}>
            <table className="tbl">
              <thead>
                <tr>
                  {shown.map((e) => (
                    <th key={e.field}>{humanLabel(e.field, e.label)}</th>
                  ))}
                  {!readOnly && <th aria-label="row actions"></th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    {shown.map((entry) => renderCell(entry, row, index))}
                    {!readOnly && (
                      <td>
                        <button
                          className="btn btn-small btn-danger"
                          aria-label={`Remove row ${index + 1}`}
                          onClick={() => removeRow(index)}
                        >
                          ✕
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {advancedCols.length > 0 && (
              <details className="subtle">
                <summary>
                  Advanced physical configuration — clock and power domains
                </summary>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Kind</th>
                      {advancedCols.map((e) => (
                        <th key={e.field}>{humanLabel(e.field, e.label)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={index}>
                        <td>{String((row as Record<string, unknown>)?.['kind'] ?? '—')}</td>
                        {advancedCols.map((entry) => renderCell(entry, row, index))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
            {meta.length > 0 && (
              <details className="subtle">
                <summary>
                  Interface metadata — declared, not interpreted by current simulation
                </summary>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Kind</th>
                      {meta.map((e) => (
                        <th key={e.field}>{humanLabel(e.field, e.label)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={index}>
                        <td>{String((row as Record<string, unknown>)?.['kind'] ?? '—')}</td>
                        {meta.map((entry) => renderCell(entry, row, index))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
            {!readOnly && canAddRows(rowsPath) && (
              <button className="btn btn-small" onClick={addRow}>
                Add row
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}

export default function DesignViewV2Editor({
  view, doc, onDocChange, onGoToSection, readOnly = false,
  sectionId, onSectionChange, projectId,
}: {
  view: DesignViewV2;
  doc: Record<string, unknown>;
  onDocChange: (next: Record<string, unknown>) => void;
  onGoToSection: (owner: string) => void;
  readOnly?: boolean;
  sectionId: string;
  onSectionChange: (id: string) => void;
  projectId?: string;
}): ReactElement {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const section = useMemo(
    () => view.sections.find((s) => s.id === sectionId) ?? view.sections[0],
    [view.sections, sectionId]);

  const primary = (section?.entries.filter(
    (e) => e.disclosure_depth === 'GUIDED' && LOCATIONS[e.field]?.kind === 'scalar') ?? []);
  const advanced = (section?.entries.filter(
    (e) => e.disclosure_depth === 'EXPERT' && LOCATIONS[e.field]?.kind === 'scalar') ?? []);
  const managed = (section?.entries.filter(
    (e) => !LOCATIONS[e.field]) ?? []);
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

  const renderEntry = (entry: (typeof primary)[number]): ReactElement | null => {
    const location = LOCATIONS[entry.field];
    if (!location || location.kind === 'row') return null;
    if (entry.field === 'NocConfig.topology_family') {
      const current = readScalar(doc, ['noc_config', 'topology_family']);
      return (
        <div key={entry.field} className="field field-topology">
          <span className="field-label">{humanLabel(entry.field, entry.label)}</span>
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
          {humanLabel(entry.field, entry.label)}
          {entry.source === 'RECOMMENDATION' && (
            <span className="field-hint" title="Guided default — change it only if you mean it"> ◆</span>
          )}
        </span>
        <EntryInput entry={entry} doc={doc}
                    onChange={onChangeDoc} readOnly={readOnly} />
      </label>
    );
  };
  const onChangeDoc = (next: Record<string, unknown>): void => {
    onDocChange(next);
  };

  return (
    <div className="design-v2" data-workbench-group={group}>
      <nav className="section-nav" aria-label="Design sections">
        {WORKBENCH_GROUPS.map((g) => {
          const items = view.sections.filter((s) => sectionGroup(s) === g);
          if (items.length === 0) return null;
          return (
            <div key={g}>
              <div className="section-nav-group">{GROUP_LABELS[g]}</div>
              {items.map((s) => (
                <button
                  key={s.id}
                  className={`section-nav-item${s.id === section?.id ? ' active' : ''}`}
                  aria-current={s.id === section?.id ? 'true' : undefined}
                  onClick={() => onSectionChange(s.id)}
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
            </div>
          );
        })}
      </nav>

      <div className="design-v2-main">
        <h3>{section?.title}</h3>
        <p className="muted prov-legend">
          <Prov kind="EDITABLE" /> authored intent
          {' · '}
          <Prov kind="DERIVED" /> compiler output
          {' · '}
          <Prov kind="PROFILE" /> descriptive metadata
        </p>

        {(section?.entries.length ?? 0) === 0 ? (
          <EmptySection
            sectionId={section?.id ?? ''}
            doc={doc}
            onChange={onChangeDoc}
            readOnly={readOnly}
          />
        ) : (
          <>
            {hasParallelism && <ParallelismPreview doc={doc} />}
            {section?.id === 'workload' && (
              <WorkloadSwitcher projectId={projectId} />
            )}
            {hasAgents && <AgentSummary doc={doc} />}
            {section?.id === 'communication' && (
              <CommunicationSummary doc={doc} />
            )}

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
                    <span className="field-label">
                      {humanLabel(entry.field, entry.label)}
                      {entry.source === 'RECOMMENDATION' && (
                        <span className="field-hint" title="Guided default — change it only if you mean it"> ◆</span>
                      )}
                    </span>
                    <EntryInput entry={entry} doc={doc}
                                onChange={onChangeDoc} readOnly={readOnly} />
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        <RoutingResourcesNote show={hasArbitration} />

        {isGoals && <AnalysisGoals projectId={projectId} />}

        {managed.length > 0 && (
          <details className="subtle">
            <summary>
              Backend-managed fields ({managed.length}) — no Studio control writes these
            </summary>
            <ul className="muted">
              {managed.map((entry) => (
                <li key={entry.field}>
                  {humanLabel(entry.field, entry.label)}
                </li>
              ))}
            </ul>
          </details>
        )}
          </>
        )}

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
