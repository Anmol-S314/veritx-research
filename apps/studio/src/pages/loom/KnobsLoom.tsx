import { useMemo, useState, type ReactElement } from 'react';
import { navigate } from '../../router';
import { useAsync, useStudio } from '../../studio';
import { api } from '../../api';
import type {
  BackendKnobRow, FabricPresetCatalogEntry, KnobInventoryView,
} from '../../api';
import { From, Kv, Panes, RailSection, SummaryStrip, type StripTone } from './parts';

/** Colour only. The word on screen is always the one the server sent; this
 *  decides how it is tinted and nothing about whether a knob is editable.
 *
 *  Deliberately keyed off the audit's own flags rather than its owner words:
 *  the Loom provenance vocabulary is reserved for the From line, and a second
 *  copy of it here would be exactly the drift that contract exists to stop. */
function toneOf(row: BackendKnobRow): StripTone {
  if (row.overridable) return 'ok';
  if (row.inactive) return 'bad';
  if (!row.audited) return 'warn';
  return 'info';
}

const ALL = 'all';

/** Why a row is not editable, read off the server's own owner word. This
 *  states the reason; it never decides it, and an unknown owner falls through
 *  to a sentence that admits it does not know rather than guessing. */
function editableReason(row: BackendKnobRow): string {
  if (row.control) return `authored today through the ${row.control} control`;
  if (row.overridable) return 'a pinned profile constant a controlled profile may replace';
  if (row.owner === 'INACTIVE_FOR_PROFILE') return 'inactive for this profile — it is never read';
  if (row.derived) return `derived from the compiled design (${row.owner}), not a knob`;
  if (!row.audited) return 'no audited read site — overriding it needs an audit row first';
  return `owner ${row.owner}; the audit decides whether it may be replaced`;
}

/** The backend knob surface and the shipped operations, in one place.
 *
 *  Two questions a design surface must answer together: what can the
 *  simulator be told (the fork's real registration, classified by the profile
 *  audit), and what can I run right now (the shipped presets, materialized on
 *  demand). Nothing here is hand-listed: the knobs come from the engine's own
 *  source plus its audit, and the operations come from the preset catalog.
 */
export default function KnobsLoom(): ReactElement {
  const { refreshProjects, setActiveProjectId } = useStudio();
  const inventory = useAsync<KnobInventoryView>(() => api.knobInventory(), []);
  const presets = useAsync(() => api.fabricPresets(), []);

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<string>(ALL);
  const [owner, setOwner] = useState<string>(ALL);
  const [onlyEditable, setOnlyEditable] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const backend = inventory.result.state === 'ready'
    ? inventory.result.data.backend ?? null : null;
  const knobs = backend?.knobs ?? [];

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return knobs.filter((row) => {
      if (category !== ALL && row.category !== category) return false;
      if (owner !== ALL && row.owner !== owner) return false;
      if (onlyEditable && !row.overridable && !row.control) return false;
      if (!needle) return true;
      return row.name.toLowerCase().includes(needle)
        || row.source.toLowerCase().includes(needle)
        || row.note.toLowerCase().includes(needle);
    });
  }, [knobs, search, category, owner, onlyEditable]);

  const current = rows.find((r) => r.name === selected)
    ?? knobs.find((r) => r.name === selected) ?? null;

  const openPreset = async (entry: FabricPresetCatalogEntry): Promise<void> => {
    setBusy(entry.preset_id);
    setFailure(null);
    try {
      const view = await api.createProjectFromPreset(entry.preset_id);
      const id = view.project.project_id;
      if (!id) throw new Error('the engine returned no project id');
      // The shell resolves a project route against the list it already holds,
      // so a project the engine just created is unknown to it. Both halves are
      // needed: point the shell at the new id, and refetch the list so the
      // route resolves as a project rather than falling back to the picker.
      setActiveProjectId(id);
      refreshProjects();
      navigate(`/projects/${id}/design`);
    } catch (error: unknown) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const left = (
    <>
      <RailSection title="Filters" note="Text matches names, the source location the audit records, and each knob's own note.">
        <label className="loom-field">
          <span>name / source / note</span>
          <input id="knob-search" name="knob-search" type="search" value={search}
            placeholder="e.g. pair_stats, trafficmanager.cpp"
            onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="loom-field">
          <span>category</span>
          <select id="knob-category" name="knob-category" value={category}
            onChange={(e) => setCategory(e.target.value)}>
            <option value={ALL}>all categories</option>
            {Object.keys(backend?.by_category ?? {}).map((c) => (
              <option key={c} value={c}>{c} ({backend?.by_category[c]})</option>
            ))}
          </select>
        </label>
        <label className="loom-field">
          <span>owner</span>
          <select id="knob-owner" name="knob-owner" value={owner}
            onChange={(e) => setOwner(e.target.value)}>
            <option value={ALL}>all owners</option>
            {Object.keys(backend?.by_owner ?? {}).map((o) => (
              <option key={o} value={o}>{o} ({backend?.by_owner[o]})</option>
            ))}
          </select>
        </label>
        <label className="loom-field">
          <span>only replaceable</span>
          <input type="checkbox" checked={onlyEditable}
            onChange={(e) => setOnlyEditable(e.target.checked)} />
        </label>
      </RailSection>
      <RailSection title="What the owners mean"
        note="These are the engine's words. The colour beside each row only tints it.">
        <p className="muted">
          <b className="t-ok">BACKEND_PROFILE</b> — a pinned constant a controlled
          profile may replace. This is the fine-grained control surface.
        </p>
        <p className="muted">
          <b className="t-info">derived owners</b> (for example FABRIC_DERIVED,
          WORKLOAD_DERIVED) — computed from the compiled design; overriding one
          would contradict it.
        </p>
        <p className="muted">
          <b className="t-bad">INACTIVE_FOR_PROFILE</b> — the profile means to read
          it and never does.
        </p>
        <p className="muted">
          <b className="t-warn">UNAUDITED</b> — the binary accepts it, no audited
          profile reads it. Listed so a hidden knob is visible, not because the
          product owns it.
        </p>
      </RailSection>
    </>
  );

  const presetList = presets.result.state === 'ready'
    ? presets.result.data.presets : [];

  const stage = (
    <>
      <SummaryStrip items={[
        { k: 'registered by the fork', v: backend?.total ?? '—', tone: 'info' },
        { k: 'with an audited read site', v: backend?.audited ?? '—', tone: 'ok' },
        { k: 'replaceable by a controlled profile', v: backend?.overridable ?? '—', tone: 'ok' },
        { k: 'authored today', v: backend?.controllable ?? '—', tone: 'info' },
        { k: 'knobs shown after filters', v: rows.length, tone: 'info' },
      ]} />

      <section className="loom-section">
        <h2 className="loom-section-title">
          Ready-to-run operations — {presetList.length}
        </h2>
        <p className="loom-note">
          Each operation materializes the preset's own canonical request as an
          editable draft. The engine builds it; this screen does not copy it.
        </p>
        {presets.result.state === 'error' && (
          <p className="t-bad" role="alert">
            ✗ preset catalog unreadable: {presets.result.error.message}
          </p>
        )}
        {presets.result.state === 'loading' && (
          <p className="muted" role="status">Reading the preset catalog…</p>
        )}
        {failure && <p className="t-bad" role="alert">✗ {failure}</p>}
        {presetList.length > 0 && (
          <div className="loom-table-wrap">
            <table className="tbl loom-table">
              <thead>
                <tr>
                  <th>Preset</th>
                  <th>Family</th>
                  <th>Gen</th>
                  <th className="num">Deps</th>
                  <th>What it builds</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {presetList.map((entry) => (
                  <tr key={entry.preset_id}>
                    <td className="num">{entry.preset_id}</td>
                    <td>{entry.family || '—'}</td>
                    <td>{entry.generation ?? '—'}</td>
                    <td className="num">{entry.dependencies.length}</td>
                    <td>{entry.description}</td>
                    <td>
                      <button className="btn btn-small" disabled={busy !== null}
                        onClick={(e) => { e.stopPropagation(); void openPreset(entry); }}>
                        {busy === entry.preset_id ? 'Materializing…' : 'Create & open'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="loom-section">
        <h2 className="loom-section-title">
          Backend knobs — {rows.length} of {backend?.total ?? 0}
        </h2>
        {inventory.result.state === 'loading' && (
          <p className="muted" role="status">Reading the engine's knob surface…</p>
        )}
        {inventory.result.state === 'error' && (
          <p className="t-bad" role="alert">
            ✗ knob inventory unreadable: {inventory.result.error.message}
          </p>
        )}
        {backend && backend.total === 0 && (
          <p className="muted">
            {backend.note ?? 'the backend reports no knobs on this tree'}
          </p>
        )}
        {backend && backend.total > 0 && (
          <div className="loom-table-wrap">
            <table className="tbl loom-table">
              <thead>
                <tr>
                  <th>Knob</th>
                  <th>Category</th>
                  <th>Owner</th>
                  <th>Default</th>
                  <th>Editable</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name}
                    className={row.name === selected ? 'sel' : undefined}
                    onClick={() => setSelected(row.name)}>
                    <td className="num">{row.name}</td>
                    <td>{row.category}</td>
                    <td className={`t-${toneOf(row)}`}>
                      {row.owner}
                    </td>
                    <td className="num">
                      {row.default === null ? '—' : JSON.stringify(row.default)}
                    </td>
                    <td>{row.control ? 'control' : row.overridable ? 'replaceable' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );

  const right = current ? (
    <RailSection title="Knob inspector">
      <From origin="DECLARED" artifact="backend" data={null}
        note="the fork's own knob registration joined with the profile audit; a property of the installed backend, not of this revision" />
      <Kv label="Name" value={<code>{current.name}</code>} />
      <Kv label="Category" value={current.category} />
      <Kv label="Owner" value={current.owner} />
      <Kv label="Type" value={current.type} />
      <Kv label="Default" value={current.default === null ? '—' : JSON.stringify(current.default)} mono />
      <Kv label="Pinned" value={current.pinned === null || current.pinned === undefined
        ? '—' : JSON.stringify(current.pinned)} mono />
      <Kv label="Read at" value={current.source} mono />
      <Kv label="Audited" value={current.audited ? 'yes' : 'no'} />
      <Kv label="Vector spelling" value={current.vector_spelling ? 'yes' : 'no'} />
      <Kv label="Authored control" value={current.control ?? '—'} />
      <p className="loom-note">
        {current.note || 'the fork registers this knob without an audit note'}
      </p>
      <p className="muted">{editableReason(current)}</p>
    </RailSection>
  ) : (
    <RailSection title="Knob inspector">
      <p className="muted">Select a row to see where the engine reads it and why
        it is or is not editable.</p>
    </RailSection>
  );

  return (
    <Panes left={left} stage={stage} right={right} />
  );
}
