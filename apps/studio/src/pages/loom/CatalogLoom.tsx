import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import { api } from '../../api';
import { useAsync } from '../../studio';
import { Hash, humanize } from '../../components/badges';
import { agentRows, type AgentRow, type LoomData } from './data';
import { ExtensionPoint, Kv, Panes, RailSection, SummaryStrip } from './parts';

/** The engine's typed agent kinds. This list is the `AgentKind` enum in
 *  veritx_dse/model/compile_model.py:191 — five members, closed. A card is
 *  therefore a *kind*, not a purchasable IP with a part number: the contract
 *  has no vendor, no version and no licence, and inventing one would put a
 *  fictional identity next to a real count. */
const KIND_ROLE: Record<string, string> = {
  compute_tile: 'Initiator · tensor-parallel rank',
  hbm_controller: 'Target · memory',
  nic: 'Initiator/target · host',
  peripheral: 'Target · device',
  ucie_port: 'Target · die-to-die',
};

const KIND_CLASS: Record<string, string> = {
  compute_tile: 'Compute',
  hbm_controller: 'Memory',
  nic: 'Bridges',
  peripheral: 'Bridges',
  ucie_port: 'Bridges',
};

const CATEGORIES = ['All', 'Compute', 'Memory', 'Bridges'] as const;
type Category = typeof CATEGORIES[number];

const categoryOf = (kind: string): Category =>
  (KIND_CLASS[kind] as Category | undefined) ?? 'Bridges';

interface KindCard {
  kind: string;
  declared: number;
  seated: number;
  protocols: string[];
  dataWidths: number[];
  addrWidths: number[];
  clockDomains: string[];
  powerDomains: string[];
  routers: number;
  ranks: number;
}

/** One card per agent kind, built from two artifacts: the authored group rows
 *  (what was declared) and the certified attachment (what was seated). A kind
 *  declared but never seated still gets a card, with `seated: 0` — that is a
 *  finding, not a reason to hide it. */
function kindCards(rows: AgentRow[]): KindCard[] {
  const byKind = new Map<string, AgentRow[]>();
  for (const r of rows) {
    const list = byKind.get(r.kind) ?? [];
    list.push(r);
    byKind.set(r.kind, list);
  }
  const uniqSorted = (values: (string | null)[]): string[] => (
    [...new Set(values.map((v) => v ?? '—'))].sort()
  );
  return [...byKind.entries()].map(([kind, list]) => ({
    kind,
    declared: list.length,
    seated: list.filter((r) => r.attached).length,
    protocols: uniqSorted(list.map((r) => r.protocol)),
    dataWidths: [...new Set(list.map((r) => r.dataWidth).filter(
      (v): v is number => v != null,
    ))].sort((a, b) => a - b),
    addrWidths: [...new Set(list.map((r) => r.addrWidth).filter(
      (v): v is number => v != null,
    ))].sort((a, b) => a - b),
    clockDomains: uniqSorted(list.map((r) => r.clockDomain)),
    powerDomains: uniqSorted(list.map((r) => r.powerDomain)),
    routers: new Set(list.map((r) => r.routerId).filter(
      (v): v is number => v != null,
    )).size,
    ranks: list.length,
  })).sort((a, b) => b.declared - a.declared || a.kind.localeCompare(b.kind));
}

export default function CatalogLoom({ data, problems }: {
  data: LoomData;
  problems?: ReactNode;
}): ReactElement {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<Category>('All');
  const [pinned, setPinned] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const rows = useMemo(() => agentRows(data), [data]);
  const cards = useMemo(() => kindCards(rows), [rows]);
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const presets = useAsync(api.fabricPresets, []);
  const workloads = useAsync(api.workloadCatalog, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cards.filter((c) => (
      (category === 'All' || categoryOf(c.kind) === category)
      && (q === '' || c.kind.includes(q)
        || c.protocols.some((p) => p.toLowerCase().includes(q))
        || KIND_ROLE[c.kind]?.toLowerCase().includes(q))
    ));
  }, [cards, search, category]);

  const pick = selected ? cards.find((c) => c.kind === selected) ?? null : null;
  const comparing = cards.filter((c) => pinned.includes(c.kind));
  const declaredTotal = cards.reduce((n, c) => n + c.declared, 0);
  const seatedTotal = cards.reduce((n, c) => n + c.seated, 0);

  const togglePin = (kind: string): void => setPinned((current) => (
    current.includes(kind)
      ? current.filter((k) => k !== kind)
      : current.length >= 3 ? current : [...current, kind]
  ));

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Search primitives"
            note="Matches the kind, its protocol, or the role it plays on the fabric."
          >
            <label className="loom-field">
              <span>kind / protocol / role</span>
              <input
                id="loom-catalog-search"
                name="catalog-search"
                type="search"
                value={search}
                placeholder="compute, AXI, memory"
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <div className="loom-chips" role="group" aria-label="Category">
              {CATEGORIES.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`loom-chip${category === c ? ' active' : ''}`}
                  aria-pressed={category === c}
                  onClick={() => setCategory(c)}
                >
                  {c}
                </button>
              ))}
            </div>
          </RailSection>

          <RailSection
            title="Compare"
            note="Pin up to three kinds to put their authored contract side by side."
          >
            {pinned.length === 0 ? (
              <p className="muted">Nothing pinned. Use Compare on a card.</p>
            ) : (
              <ul className="loom-pin-list">
                {comparing.map((c) => (
                  <li key={c.kind}>
                    <code>{c.kind}</code>
                    <button
                      type="button"
                      className="loom-chip"
                      onClick={() => togglePin(c.kind)}
                    >
                      unpin
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </RailSection>

          <RailSection
            title="Shipped fabric presets"
            note="Real presets from the engine's preset catalog, each a starting design."
          >
            {presets.result.state === 'loading' && (
              <p className="muted" role="status">loading presets…</p>
            )}
            {presets.result.state === 'ready' && (
              <table className="tbl">
                <thead>
                  <tr><th>preset</th><th>gen</th></tr>
                </thead>
                <tbody>
                  {presets.result.data.presets.map((p) => (
                    <tr key={p.preset_id}>
                      <td title={p.description}><code>{p.preset_id}</code></td>
                      <td className="muted">v{p.generation?.replace('v', '')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="loom-note">
              A preset is a whole design, not a primitive. Applying one is a
              Design-page action; this catalog lists what exists.
            </p>
          </RailSection>

          <RailSection
            title="Not in the contract"
            note="Named so the gap against a real IP catalog is explicit."
          >
            <ul className="loom-needs">
              <li><b>Vendor, part number, version, licence</b> — the agent record is a kind and a count</li>
              <li><b>Per-IP parameters (array rows, SRAM, channels)</b> — a kind carries no configuration surface</li>
              <li><b>Area, power, fmax per primitive</b> — needs a PPA model keyed by kind and configuration</li>
              <li><b>Footprint / die area</b> — needs a physical view per primitive</li>
              <li><b>Composition (an NPU as MAC array + SRAM + DMA)</b> — the model is flat by kind</li>
              <li><b>Protocol bridges between incompatible kinds</b> — no bridge registry exists</li>
            </ul>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Kinds in use', v: String(cards.length), tone: 'info' },
            { k: 'Declared agents', v: String(declaredTotal) },
            { k: 'Seated', v: topology ? String(seatedTotal) : 'no topology' },
            { k: 'Unseated', v: topology
              ? String(declaredTotal - seatedTotal)
              : '—',
              tone: topology && declaredTotal !== seatedTotal ? 'warn' : undefined },
            { k: 'Shown', v: `${filtered.length} of ${cards.length}` },
          ]} />

          {cards.length === 0 ? (
            <ExtensionPoint
              title="No primitives instantiated"
              needs="an agents block on the draft. The catalog lists the kinds a design actually uses, so with no agents there is nothing to list."
            />
          ) : (
            <>
              <div className="loom-cards">
                {filtered.map((c) => (
                  <article
                    key={c.kind}
                    className={`loom-card${selected === c.kind ? ' sel' : ''}`}
                    onClick={() => setSelected(c.kind)}
                  >
                    <header>
                      <b>{humanize(c.kind)}</b>
                      <span className="loom-card-cat">{categoryOf(c.kind)}</span>
                    </header>
                    <p className="loom-card-role">{KIND_ROLE[c.kind] ?? 'role not declared'}</p>
                    <dl className="loom-card-spec">
                      <div><dt>declared</dt><dd className="num">{c.declared}</dd></div>
                      <div>
                        <dt>seated</dt>
                        <dd className={c.seated === c.declared ? 'num' : 'num warn'}>
                          {c.seated}
                        </dd>
                      </div>
                      <div><dt>data width</dt><dd className="num">{c.dataWidths.join('/') || '—'}</dd></div>
                      <div><dt>addr width</dt><dd className="num">{c.addrWidths.join('/') || '—'}</dd></div>
                      <div><dt>protocol</dt><dd>{c.protocols.join(', ')}</dd></div>
                      <div><dt>routers</dt><dd className="num">{c.routers || '—'}</dd></div>
                    </dl>
                    <footer>
                      <button
                        type="button"
                        className="loom-chip"
                        onClick={(e) => { e.stopPropagation(); togglePin(c.kind); }}
                        disabled={!pinned.includes(c.kind) && pinned.length >= 3}
                      >
                        {pinned.includes(c.kind) ? 'Pinned' : 'Compare'}
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
              {filtered.length === 0 && (
                <p className="muted">No primitive matches that search.</p>
              )}
              <p className="loom-hint">
                Counts are authored intent; seating is what the compiler did.
                A card with fewer seated than declared agents is an attachment
                finding, not a rendering difference.
              </p>
            </>
          )}

          {comparing.length > 0 && (
            <RailSection
              title={`Comparing ${comparing.length} kind${comparing.length === 1 ? '' : 's'}`}
              note="Every column is an authored or certified field. A dash means the value does not exist, not zero."
            >
              <div className="loom-table-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>field</th>
                      {comparing.map((c) => (
                        <th key={c.kind}><code>{c.kind}</code></th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {([
                      ['role', (c: KindCard) => KIND_ROLE[c.kind] ?? '—'],
                      ['declared agents', (c: KindCard) => String(c.declared)],
                      ['seated agents', (c: KindCard) => String(c.seated)],
                      ['routers used', (c: KindCard) => String(c.routers || '—')],
                      ['data width (b)', (c: KindCard) => c.dataWidths.join('/') || '—'],
                      ['addr width (b)', (c: KindCard) => c.addrWidths.join('/') || '—'],
                      ['protocol', (c: KindCard) => c.protocols.join(', ') || '—'],
                      ['clock domains', (c: KindCard) => c.clockDomains.join(', ') || '—'],
                      ['power domains', (c: KindCard) => c.powerDomains.join(', ') || '—'],
                    ] as [string, (c: KindCard) => string][]).map(([label, read]) => (
                      <tr key={label}>
                        <td>{label}</td>
                        {comparing.map((c) => (
                          <td key={c.kind}>{read(c)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </RailSection>
          )}
        </div>
      }
      right={
        <>
          <RailSection title="Primitive inspector">
            {pick ? (
              <>
                <Kv label="kind" value={<code>{pick.kind}</code>} />
                <Kv label="category" value={categoryOf(pick.kind)} />
                <Kv label="role" value={KIND_ROLE[pick.kind] ?? 'not declared'} />
                <Kv label="declared agents" value={String(pick.declared)} mono />
                <Kv label="seated agents" value={String(pick.seated)} mono />
                <Kv label="routers" value={String(pick.routers)} mono />
                <Kv label="data width" value={pick.dataWidths.length
                  ? `${pick.dataWidths.join(' / ')} bits`
                  : '—'} mono />
                <Kv label="addr width" value={pick.addrWidths.length
                  ? `${pick.addrWidths.join(' / ')} bits`
                  : '—'} mono />
                <Kv label="protocol" value={pick.protocols.join(', ') || '—'} />
                <Kv label="clock domain" value={pick.clockDomains.join(', ') || '—'} />
                <Kv label="power domain" value={pick.powerDomains.join(', ') || '—'} />
                <p className="loom-note">
                  A kind is a member of the engine's closed{' '}
                  <code>AgentKind</code> enum. It carries a count and an
                  interface width and nothing else — so this card has no area,
                  no power and no part number to show.
                </p>
                <Link className="link" to={`/projects/${data.projectId}/loom/agents`}>
                  See the {pick.declared} instance rows →
                </Link>
              </>
            ) : (
              <p className="muted">Select a primitive to inspect its record.</p>
            )}
          </RailSection>

          <RailSection
            title="Cross-check: catalog workloads"
            note="Workload profiles the gateway ships, with the agent kinds each one declares."
          >
            {workloads.result.state === 'loading' && (
              <p className="muted" role="status">loading workloads…</p>
            )}
            {workloads.result.state === 'ready' && (
              <table className="tbl">
                <thead>
                  <tr><th>workload</th><th>agents</th></tr>
                </thead>
                <tbody>
                  {workloads.result.data.workloads.map((w) => (
                    <tr key={w.workload_id}>
                      <td title={w.description}>
                        {w.display_name}
                        <div className="muted">
                          <Hash value={w.content_digest} />
                        </div>
                      </td>
                      <td>
                        {w.agents.map((a) => (
                          <div key={a.kind} className="num">
                            {a.count}× {a.kind}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </RailSection>

          {problems}
        </>
      }
    />
  );
}