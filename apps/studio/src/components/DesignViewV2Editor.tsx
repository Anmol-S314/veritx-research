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
  sectionId, onSectionChange,
}: {
  view: DesignViewV2;
  doc: Record<string, unknown>;
  onDocChange: (next: Record<string, unknown>) => void;
  onGoToSection: (owner: string) => void;
  /** Review presents canonical completeness; authoring is editable. */
  readOnly?: boolean;
  sectionId: string;
  onSectionChange: (id: string) => void;
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

  return (
    <div className="design-v2">
      <nav className="section-nav" aria-label="Design sections">
        {view.sections.map((s) => (
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
      </nav>

      <div className="design-v2-main">
        <h3>{section?.title}</h3>

        <div className="form-grid">
          {primary.map((entry) => (
            <label key={entry.field} className="field">
              <span className="field-label">
                {entry.label}
                {entry.source === 'RECOMMENDATION' && (
                  <span className="field-hint"> ◆ recommended</span>
                )}
              </span>
              <EntryInput entry={entry} doc={doc}
                          onChange={onDocChange} readOnly={readOnly} />
              <span className="field-owner muted">
                {entry.ownership.domain}
                {entry.ownership.scientific_name
                  ? ` · ${entry.ownership.scientific_name}` : ''}
              </span>
            </label>
          ))}
        </div>

        <RowTable section={section!} doc={doc} onChange={onDocChange}
                  readOnly={readOnly} />

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

        <div className="findings">
          {view.validation_findings.map((finding, index) => (
            <Finding key={index} finding={finding} onGoTo={onGoToSection} />
          ))}
        </div>
      </div>
    </div>
  );
}

export { READINESS_LABEL, FINDING_GLYPH, FINDING_LABEL };
