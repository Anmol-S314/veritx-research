/** The canonical mutation seam of the Loom workspace (program §56–§57).
 *
 * Every edit the workspace can make is a TYPED COMMAND here — never a
 * component writing arbitrary JSON. A command names the canonical field it
 * touches (the agent record's own keys), applies to a draft request document,
 * and carries its inverse, which is what undo/redo operates on. Commands run
 * against the local working copy only; the server stays the authority because
 * the copy is saved through the existing `PUT /projects/{id}/draft` seam,
 * which re-parses the whole document with `parse_request_doc` (strict: unknown
 * keys refuse). A command that produced an invalid document would be rejected
 * there, and the failure surfaces without corrupting the stored draft.
 *
 * Invariant list, each enforced below:
 *  - commands touch ONLY keys the v4 agent record already declares (no new
 *    fields, no schema invention in React);
 *  - stable identity: commands address a group by INDEX into `agents`, the
 *    same axis `draft.agents[group_index=…]` selection uses — a command never
 *    reorders or renumbers groups;
 *  - every command has an exact inverse, so undo restores byte-equality of
 *    the working copy (asserted by the contract test);
 *  - a command whose preconditions do not hold REFUSES (returns the document
 *    unchanged and reports why) rather than writing a partial edit.
 */

/** The seven authored fields of one agent group, verbatim from the engine's
 *  Agent dataclass. This union is the closed set Loom may write. */
import { baseDocument, withBaseDocument, assertExactJsonNumbers } from '../../canonicalDraft';

export type AgentField =
  | 'count'
  | 'data_width'
  | 'addr_width'
  | 'protocol'
  | 'clock_domain'
  | 'power_domain';

const AGENT_FIELDS: ReadonlySet<string> = new Set<AgentField>([
  'count', 'data_width', 'addr_width', 'protocol',
  'clock_domain', 'power_domain',
]);

export type DraftCommand =
  | { readonly type: 'set_agent_field'; readonly group: number;
      readonly field: AgentField; readonly value: number | string | null;
      readonly remove?: boolean }
  | { readonly type: 'set_agent_kind'; readonly group: number;
      readonly value: string }
  | { readonly type: 'set_topology_field';
      readonly field: 'radix' | 'concentration'; readonly value: number | null };

export interface CommandOutcome {
  /** The new working document, or the input unchanged when refused. */
  readonly doc: Record<string, unknown>;
  /** null on success; the refusal reason otherwise (never a silent no-op). */
  readonly refused: string | null;
  /** The inverse command (success only): applying it restores `doc`'s input. */
  readonly inverse: DraftCommand | null;
}

function agentsOf(doc: Record<string, unknown>): unknown[] | null {
  const agents = baseDocument(doc).agents;
  return Array.isArray(agents) ? agents : null;
}

function groupAt(doc: Record<string, unknown>, group: number):
    { record: Record<string, unknown> } | string {
  const agents = agentsOf(doc);
  if (agents === null) return 'the draft carries no agents block';
  if (!Number.isInteger(group) || group < 0 || group >= agents.length) {
    return `the draft declares no agent group ${group} `
      + `(it has ${agents.length})`;
  }
  const entry = agents[group];
  if (!entry || typeof entry !== 'object') {
    return `agent group ${group} is not a record`;
  }
  return { record: entry as Record<string, unknown> };
}

/** Structural copy on write: only the addressed group is cloned, so identity
 *  of every other part of the document is preserved by reference. */
function withGroup(doc: Record<string, unknown>, group: number,
    update: (record: Record<string, unknown>) => void): Record<string, unknown> {
  const agents = agentsOf(doc)!;
  const nextAgents = agents.slice();
  const record = { ...(nextAgents[group] as Record<string, unknown>) };
  update(record);
  nextAgents[group] = record;
  return withBaseDocument(doc, { ...baseDocument(doc), agents: nextAgents });
}

export function applyCommand(
    doc: Record<string, unknown>, command: DraftCommand): CommandOutcome {
  const refuse = (why: string): CommandOutcome =>
    ({ doc, refused: why, inverse: null });

  if (doc.schema_version === 5) {
    try { assertExactJsonNumbers(doc); }
    catch (err) { return refuse(err instanceof Error ? err.message : String(err)); }
  }
  switch (command.type) {
    case 'set_agent_field': {
      if (!AGENT_FIELDS.has(command.field)) {
        // Defensive: the union closes this, but a runtime cast must not be
        // able to widen the writable surface.
        return refuse(`field ${String(command.field)} is not one of the `
          + 'seven authored agent fields');
      }
      const at = groupAt(doc, command.group);
      if (typeof at === 'string') return refuse(at);
      const previous = at.record[command.field];
      if (!command.remove && command.value === previous) {
        return refuse(`agent group ${command.group} already carries `
          + `${String(command.field)}=${JSON.stringify(previous)}`);
      }
      if (command.remove && !['clock_domain', 'power_domain'].includes(command.field)) {
        return refuse('only optional domain keys may be removed');
      }
      if (command.field === 'count'
          && (typeof command.value !== 'number'
              || !Number.isInteger(command.value)
              || command.value < 1)) {
        return refuse('count must be a positive integer, got '
          + JSON.stringify(command.value));
      }
      if ((command.field === 'data_width' || command.field === 'addr_width')
          && (typeof command.value !== 'number'
              || !Number.isInteger(command.value)
              || command.value < 8)) {
        return refuse(`${command.field} must be an integer of at least 8 bits`)
      }
      if ((command.field === 'protocol')
          && (typeof command.value !== 'string' || command.value === '')) {
        return refuse('protocol must be a non-empty string');
      }
      if ((command.field === 'clock_domain' || command.field === 'power_domain')
          && command.value !== null
          && (typeof command.value !== 'string' || command.value === '')) {
        return refuse(`${command.field} must be a domain name or null`);
      }
      return {
        doc: withGroup(doc, command.group, (r) => {
          if (command.remove) delete r[command.field];
          else r[command.field] = command.value;
        }),
        refused: null,
        inverse: {
          type: 'set_agent_field',
          group: command.group,
          field: command.field,
          value: (previous ?? null) as number | string | null,
          ...(!Object.prototype.hasOwnProperty.call(at.record, command.field) ? { remove: true } : {}),
        },
      };
    }
    case 'set_agent_kind': {
      const at = groupAt(doc, command.group);
      if (typeof at === 'string') return refuse(at);
      if (typeof command.value !== 'string' || command.value === '') {
        return refuse('kind must be a non-empty string');
      }
      const previous = at.record.kind;
      if (command.value === previous) {
        return refuse(`agent group ${command.group} already carries `
          + `kind=${JSON.stringify(previous)}`);
      }
      if (typeof previous !== 'string') {
        return refuse(`agent group ${command.group} has no kind to invert`);
      }
      return {
        doc: withGroup(doc, command.group, (r) => {
          r.kind = command.value;
        }),
        refused: null,
        inverse: { type: 'set_agent_kind', group: command.group,
                   value: previous },
      };
    }
    case 'set_topology_field': {
      if (doc.schema_version !== 2 && doc.schema_version !== 3) {
        return refuse('legacy topology controls are supported only for v2/v3 drafts');
      }
      if (command.value !== null
          && (!Number.isInteger(command.value) || command.value < 1)) {
        return refuse(`${command.field} must be a positive integer or null`);
      }
      const raw = doc.noc_config;
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return refuse('the draft carries no noc_config record');
      }
      const noc = raw as Record<string, unknown>;
      if (!['mesh', 'concentrated_mesh', 'torus'].includes(
          String(noc.topology_family))) {
        return refuse('radix/concentration editing is supported only for '
          + 'mesh, concentrated_mesh, or torus families');
      }
      if (!Object.prototype.hasOwnProperty.call(noc, command.field)) {
        return refuse(`noc_config.${command.field} is not explicitly declared`);
      }
      const previous = noc[command.field];
      if (previous !== null && (typeof previous !== 'number'
          || !Number.isInteger(previous) || previous < 1)) {
        return refuse(`noc_config.${command.field} is not a supported integer`);
      }
      if (command.value === previous) {
        return refuse(`noc_config.${command.field} already carries `
          + `${String(previous)}`);
      }
      return {
        doc: { ...doc, noc_config: { ...noc, [command.field]: command.value } },
        refused: null,
        inverse: { type: 'set_topology_field', field: command.field,
                   value: previous as number | null },
      };
    }
    default: {
      // Exhaustiveness: an unknown command type must refuse, never fall
      // through to a write.
      const never: never = command;
      return refuse(`unknown command ${JSON.stringify(never)}`);
    }
  }
}

/** Undo/redo history over working copies. Snapshots, not DOM state: each
 *  entry is the document a command produced, so undo restores it exactly and
 *  autosave (a PUT) never touches the stacks. */
export class DraftHistory {
  private past: Record<string, unknown>[] = [];
  private future: Record<string, unknown>[] = [];

  constructor(private doc: Record<string, unknown>) {}

  current(): Record<string, unknown> { return this.doc; }

  apply(command: DraftCommand): CommandOutcome {
    const outcome = applyCommand(this.doc, command);
    if (outcome.refused === null) {
      this.past.push(this.doc);
      this.future = [];
      this.doc = outcome.doc;
    }
    return outcome;
  }

  canUndo(): boolean { return this.past.length > 0; }
  canRedo(): boolean { return this.future.length > 0; }

  undo(): Record<string, unknown> | null {
    const previous = this.past.pop();
    if (previous === undefined) return null;
    this.future.push(this.doc);
    this.doc = previous;
    return this.doc;
  }

  redo(): Record<string, unknown> | null {
    const next = this.future.pop();
    if (next === undefined) return null;
    this.past.push(this.doc);
    this.doc = next;
    return this.doc;
  }

  /** Replace the working copy (server reload). History clears: the stacks
   *  described a document that no longer exists. */
  reset(doc: Record<string, unknown>): void {
    this.doc = doc;
    this.past = [];
    this.future = [];
  }
}
