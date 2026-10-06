import { useState, type ReactElement } from 'react';
import { Link, useAsync } from '../../studio';
import { api } from '../../api';
import type {
  CapabilityRow, CapabilityStatus, LoomCapabilityView, TopologyFamilyTruth,
} from '../../api';
import type { LoomData } from './data';
import {
  ExtensionPoint, Kv, Panes, RailSection, SummaryStrip, type StripTone,
} from './parts';

/** Colour only. The word on screen is always the one the server sent; this
 *  decides how it is tinted and nothing about whether a capability exists. */
function toneOf(status: CapabilityStatus): StripTone {
  switch (status) {
    case 'READY': return 'ok';
    case 'PARTIAL': return 'info';
    case 'BLOCKED': return 'warn';
    case 'UNSUPPORTED': return 'warn';
    case 'NOT_IMPLEMENTED': return 'bad';
  }
}

/** A capability the registry names and nothing implements. The status word is
 *  the server's; reading it here only decides how loudly the row is drawn. */
function isAbsent(row: CapabilityRow): boolean {
  return row.status === 'NOT_IMPLEMENTED';
}

/** What the server says a pipeline stage MEANS. Null when it shipped no
 *  sentence for it — which is stated, never filled in with our own. */
function stageMeaning(
  topology: LoomCapabilityView['topology'],
  stage: string,
): string | null {
  return topology.stage_meaning?.[stage] ?? null;
}

/** Families in the server's own pipeline order: the ones it recorded no stop
 *  for lead, then the rest by the stage they stopped at. This orders rows for
 *  reading; it decides no status, and a stop the stage_order does not name
 *  sorts last because an unrecognised stage is not evidence of completeness. */
function sortFamilies(
  families: TopologyFamilyTruth[],
  order: string[],
): TopologyFamilyTruth[] {
  const rank = (f: TopologyFamilyTruth): number => {
    if (f.stopped_at === null) return -1;
    const at = order.indexOf(f.stopped_at);
    return at === -1 ? order.length : at;
  };
  return [...families].sort(
    (a, b) => rank(a) - rank(b) || a.family.localeCompare(b.family),
  );
}

/** The one capability authority in the product, read whole.
 *
 *  Everything on this screen is a string the server returned: the statuses,
 *  the stage each family stops at, the reason behind each capability and the
 *  paths that establish it. Nothing here decides capability, and nothing is
 *  inferred from a topology name, a model name or a design value. */
export default function CapabilityLoom({ data }: { data: LoomData }): ReactElement {
  const [status, setStatus] = useState<CapabilityStatus | null>(null);
  const [search, setSearch] = useState('');

  // The probe is asked for explicitly: this view renders a topology family
  // table, and a client that offers a family choice must read the probed
  // table rather than a declared list of names.
  const registry = useAsync(() => api.loomCapabilities(true), []);

  // Three answers, never two. An unreadable registry and a registry with no
  // rows in it mean opposite things, so the failure is not folded away.
  const read = registry.result;
  const view = read.state === 'ready' ? read.data : null;
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;

  const capabilities = view?.capabilities ?? [];
  const stageOrder = view?.topology.stage_order ?? [];
  const families = sortFamilies(
    view?.topology.families ?? [], stageOrder,
  );
  // The absent rows are counted over the whole registry, not over the filter:
  // a capability the system does not have stays visible while a search runs.
  const absent = capabilities.filter(isAbsent);

  const query = search.trim().toLowerCase();
  const shown = capabilities.filter((r) => (
    (status === null || r.status === status)
    && (query === ''
      || r.id.toLowerCase().includes(query)
      || r.reason.toLowerCase().includes(query))
  ));

  const familyRow = view && topology
    ? families.find((f) => f.family === topology.family) ?? null
    : null;

  const stage = ((): ReactElement => {
    if (read.state === 'error') {
      return (
        <div className="loom-ext is-bad" role="alert">
          <div className="loom-ext-title">Registry unreadable</div>
          <p className="loom-ext-body">
            The capability registry could not be read, so no capability state
            is shown. A failed read is not an empty registry: nothing below may
            be taken as absent, refused or available, and which topology
            families this compiler can take stays unknown until the read lands.
          </p>
          <p className="loom-cap-reason t-bad">{read.error.message}</p>
          <div className="loom-actions">
            <button
              type="button"
              className="btn"
              onClick={() => registry.reload()}
            >
              Retry the read
            </button>
          </div>
        </div>
      );
    }
    if (!view) {
      return (
        <>
          <p className="muted" role="status">reading the capability registry…</p>
          <p className="loom-hint">
            The read asks the server to probe the compiler for every registered
            topology family, so the first answer takes as long as that probe
            does. Nothing is drawn before it: a capability this view guessed
            would be a capability the compiler may not have.
          </p>
        </>
      );
    }

    return (
      <div className="loom-view">
        <SummaryStrip items={[
          { k: 'Capabilities', v: String(capabilities.length), tone: 'info' },
          { k: 'Statuses declared', v: String(view.statuses.length) },
          {
            k: 'Families probed',
            v: view.topology.probed ? String(families.length) : 'not probed',
          },
          {
            k: 'No stop recorded',
            v: view.topology.probed
              ? String(families.filter((f) => f.stopped_at === null).length)
              : '—',
          },
          {
            k: 'Named, not implemented',
            v: String(absent.length),
            tone: absent.length ? 'bad' : undefined,
          },
          { k: 'Shown', v: `${shown.length} of ${capabilities.length}` },
        ]} />

        {absent.length > 0 && (
          <div
            className="loom-gap"
            role="group"
            aria-label="Capabilities the server reports as not implemented"
          >
            <div className="loom-gap-head">
              <b>Named, not implemented</b>
              <span className="t-bad">{absent.length} of {capabilities.length}</span>
            </div>
            <p className="loom-prose-body">
              Each of these has a name in the product surface and no
              implementation behind it. The paths under a reason are what
              establish the absence — read the path, not the label. This block
              counts the whole registry and ignores the filter below.
            </p>
            {absent.map((row) => (
              <div className="loom-gap-item" key={row.id}>
                <div className="loom-gap-item-head">
                  <code>{row.id}</code>
                  <span className={`t-${toneOf(row.status)}`}>{row.status}</span>
                </div>
                <p className="loom-prose-body">{row.reason}</p>
                <ul className="loom-refs">
                  {row.evidence_refs.map((ref) => (
                    <li key={ref}><code>{ref}</code></li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        <RailSection
          title="Probed topology families"
          note="Each row is a family the server compiled to find out how far it gets. Status, the stage it stops at and the qualification are the server's answer to that run; the sentence under a stage is the server's own definition of the stage."
        >
          {!view.topology.probed ? (
            <ExtensionPoint
              title="Topology probe not run"
              needs="a registry read that asks for the compiler probe. A family list is only ever what the server probed, never a name this client recognises."
            />
          ) : families.length === 0 ? (
            <ExtensionPoint
              title="No family probed"
              needs="at least one registered topology family for the server to compile. An empty probe is the server's answer; no family is invented to fill the table."
            />
          ) : (
            <div className="loom-table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th scope="col">family</th>
                    <th scope="col">status</th>
                    <th scope="col">stopped at</th>
                    <th scope="col">qualification</th>
                    <th scope="col">reason (server)</th>
                  </tr>
                </thead>
                <tbody>
                  {families.map((f) => {
                    const meaning = f.stopped_at === null
                      ? null : stageMeaning(view.topology, f.stopped_at);
                    return (
                      <tr key={f.family}>
                        <td><code>{f.family}</code></td>
                        <td>
                          <span className={`t-${toneOf(f.status)}`}>{f.status}</span>
                        </td>
                        <td>
                          {f.stopped_at === null ? (
                            <span className="muted">no stop recorded</span>
                          ) : (
                            <>
                              <code>{f.stopped_at}</code>
                              {meaning && <div className="loom-cell-sub">{meaning}</div>}
                            </>
                          )}
                        </td>
                        <td>
                          {f.qualification
                            ? <code>{f.qualification}</code>
                            : <span className="muted">—</span>}
                        </td>
                        <td className="loom-cap-reason">{f.reason}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </RailSection>

        <RailSection
          title="Capability registry"
          note="Every capability the registry returned, in the order it returned them. The reason is the server's sentence and is shown whole: it is the authoritative statement of what exists and what is missing."
        >
          <div className="loom-table-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th scope="col">capability</th>
                  <th scope="col">status</th>
                  <th scope="col">blocked at</th>
                  <th scope="col">reason (server)</th>
                  <th scope="col">evidence</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr
                    key={row.id}
                    className={isAbsent(row) ? 'loom-gap-row' : undefined}
                  >
                    <td><code>{row.id}</code></td>
                    <td>
                      <span className={`t-${toneOf(row.status)}`}>{row.status}</span>
                    </td>
                    <td>
                      {row.blocked_at
                        ? <code>{row.blocked_at}</code>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="loom-cap-reason">{row.reason}</td>
                    <td>
                      {/* In a table cell a full path has no room, so it is
                          shown truncated with the whole value on hover and in
                          the DOM. The gap block above gets them in full. */}
                      <ul className="loom-refs is-inline">
                        {row.evidence_refs.map((ref) => (
                          <li key={ref} title={ref}>
                            <code>{ref}</code>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No capability matches this filter. The registry is
                      unchanged — the filter only hid rows.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </RailSection>

        <p className="loom-hint">
          This view declares no capability of its own: every status, stage,
          reason and path above is the string the registry returned. A
          capability missing from the table is unknown, not refused, and one
          listed as not implemented is refused by reading this table — never by
          inferring it from a topology name, a model name or a design value.
        </p>
      </div>
    );
  })();

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Registry read"
            note="One request. The counts below are the server's own grouping of its own rows, not a tally this view made."
          >
            <Kv label="registry" value={view ? <code>{view.type}</code> : 'unread'} />
            <Kv label="schema" value={view ? `v${view.schema_version}` : '—'} mono />
            <Kv label="capabilities" value={view ? String(capabilities.length) : '—'} mono />
            <Kv label="families probed" value={view
              ? (view.topology.probed ? String(families.length) : 'not probed')
              : '—'} mono />
          </RailSection>

          <RailSection
            title="Counts by status"
            note="A status the server declared but never used reads 0 — its bucket is simply absent from by_status. Pick one to filter the registry table; pick it again to clear."
          >
            <div className="loom-chips" role="group" aria-label="Filter by capability status">
              <button
                type="button"
                className={`loom-chip${status === null ? ' active' : ''}`}
                aria-pressed={status === null}
                onClick={() => setStatus(null)}
              >
                all
              </button>
              {view?.statuses.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`loom-chip${status === s ? ' active' : ''}`}
                  aria-pressed={status === s}
                  onClick={() => setStatus(status === s ? null : s)}
                >
                  <span className={`t-${toneOf(s)}`}>{s}</span>{' '}
                  {view.by_status[s]?.length ?? 0}
                </button>
              ))}
            </div>
          </RailSection>

          <RailSection
            title="Find a capability"
            note="Matches the capability id or the server's reason sentence, so a gap can be found by what it says rather than by what it is called."
          >
            <label className="loom-field">
              <span>id / reason</span>
              <input
                id="loom-capability-search"
                name="capability-search"
                type="search"
                value={search}
                placeholder="capability id"
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <p className="loom-note">
              {view
                ? `${shown.length} of ${capabilities.length} shown`
                : 'the registry has not answered yet'}
            </p>
          </RailSection>

          <RailSection
            title="This revision against the registry"
            note="A join on the family name the certified topology reports. It reads the registry's probed row for that family; it never decides one."
          >
            {data.topology.result.state === 'error' ? (
              <p className="bad">
                The certified topology is unreadable, so this revision's family
                is unknown. Unknown here does not mean absent from the registry.
              </p>
            ) : !view ? (
              <p className="muted">
                The probed table arrives with the registry read.
              </p>
            ) : topology ? (
              <>
                <Kv label="revision" value={<code>{data.revisionId ?? '—'}</code>} />
                <Kv label="family" value={<code>{topology.family}</code>} />
                <Kv label="probed row" value={familyRow
                  ? <span className={`t-${toneOf(familyRow.status)}`}>{familyRow.status}</span>
                  : <span className="muted">not among the probed families</span>} />
                <Kv label="stops at" value={familyRow
                  ? (familyRow.stopped_at
                    ? <code>{familyRow.stopped_at}</code>
                    : <span className="muted">no stop recorded</span>)
                  : '—'} />
                {familyRow?.qualification && (
                  <Kv label="qualification" value={<code>{familyRow.qualification}</code>} />
                )}
                <Link className="link" to={`/projects/${data.projectId}/loom/topology`}>
                  This revision's topology →
                </Link>
              </>
            ) : (
              <p className="muted">
                No certified topology on this project, so there is no family to
                join against the probed table. The registry above is unaffected.
              </p>
            )}
          </RailSection>
        </>
      }
      stage={stage}
      right={
        view ? (
          <>
            <RailSection
              title="Server notes, verbatim"
              note="Both strings ship with the registry. Neither is paraphrased, shortened or re-worded here."
            >
              <div className="loom-prose">
                <div className="loom-prose-key">note</div>
                <p className="loom-prose-body">{view.note}</p>
              </div>
              <div className="loom-prose">
                <div className="loom-prose-key">readiness_note</div>
                <p className="loom-prose-body">{view.readiness_note}</p>
              </div>
            </RailSection>

            <RailSection
              title="What the statuses mean"
              note="The words, their membership and the counts are the server's. This panel shows which capabilities carry each word and the server's own sentence for the stage those rows stop at; it defines none of them."
            >
              <div className="loom-vocab">
                {view.statuses.map((s) => {
                  const ids = view.by_status[s] ?? [];
                  const stops = [...new Set(capabilities.flatMap((r) => (
                    r.status === s && r.blocked_at !== null ? [r.blocked_at] : []
                  )))].sort();
                  return (
                    <div className="loom-vocab-row" key={s}>
                      <div className="loom-vocab-head">
                        <span className={`t-${toneOf(s)}`}><code>{s}</code></span>
                        <span className="num">{ids.length}</span>
                      </div>
                      <p className="loom-vocab-ids">
                        {ids.length === 0
                          ? 'no capability carries this status'
                          : ids.join(' · ')}
                      </p>
                      {stops.map((stop) => {
                        const meaning = stageMeaning(view.topology, stop);
                        return (
                          <p className="loom-vocab-ids" key={stop}>
                            rows stop at <code>{stop}</code>
                            {meaning ? ` — ${meaning}` : ''}
                          </p>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </RailSection>

            {stageOrder.length > 0 && (
              <RailSection
                title="Pipeline stages"
                note="The server's stage vocabulary in the order it sent it. A family that stops at stage N is complete up to N and not beyond."
              >
                {stageOrder.map((st) => (
                  <div className="kv" key={st}>
                    <span><code>{st}</code></span>
                    <span>
                      {stageMeaning(view.topology, st)
                        ?? 'no meaning shipped for this stage'}
                    </span>
                  </div>
                ))}
              </RailSection>
            )}
          </>
        ) : (
          <RailSection
            title="Server notes"
            note="The registry carries its own account of what its statuses mean. It arrives with the read, and nothing is stood in for it."
          >
            <p className="muted">
              {read.state === 'error'
                ? 'Unreadable: the notes could not be fetched, so nothing is asserted here about what any status means.'
                : 'Loading the registry notes…'}
            </p>
          </RailSection>
        )
      }
    />
  );
}