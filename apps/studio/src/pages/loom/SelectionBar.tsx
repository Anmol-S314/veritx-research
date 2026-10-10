/** The one selection surface in the Loom workspace.
 *
 *  It sits above the tabs because selection is global: it is in the URL, so it
 *  is the same set before a tab change and after it. Every tab reads and writes
 *  this store — no tab keeps its own — and this bar is where a selection says
 *  what it is, which artifact it came from, which revision it was read from,
 *  and whether that revision still answers the design on screen.
 *
 *  The origin badge is the load-bearing part. A router is COMPILER-DERIVED, an
 *  agent instance is AUTHORED INTENT, a measured cell is MEASURED and names its
 *  run: they look identical in a table otherwise. An origin the served
 *  vocabulary does not assign is left unresolved and the reason is shown, never
 *  filled in with one of the four words.
 */
import { useRef, useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import { Kv } from './parts';
import type { LoomData, LoomViewId } from './data';
import {
  carriedKinds, freshnessTone, loomIdText, PRIMARY_VIEW, provenanceOf,
  resolveAgainstData, selectionIds, type LoomId, type SelectionProvenance,
} from './selection';
import type { LoomSelectionStore } from './selectionStore';

/** How loud an origin row is drawn. Colour only: the word beside it is the one
 *  the served vocabulary produced, and an unresolved origin stays muted rather
 *  than being given one of the four. */
function originTone(origin: string | null): string {
  switch (origin) {
    case 'AUTHORED': return 'info';
    case 'DERIVED': return 'accent';
    case 'DECLARED': return 'warn';
    case 'MEASURED': return 'ok';
    default: return 'muted';
  }
}

function Freshness({ provenance }: { provenance: SelectionProvenance }): ReactElement {
  const tone = freshnessTone(provenance.freshness.state);
  return (
    <>
      <Kv
        label="freshness"
        value={<span className={`t-${tone}`}>{provenance.freshness.state}</span>}
      />
      {provenance.freshness.note && (
        <p className="loom-note">{provenance.freshness.note}</p>
      )}
    </>
  );
}

function Provenance({ provenance, data }: {
  provenance: SelectionProvenance;
  data: LoomData;
}): ReactElement {
  const resolved = resolveAgainstData(provenance.id, data);
  return (
    <>
      <Kv
        label="origin"
        value={provenance.origin === null
          ? <span className="muted">UNRESOLVED</span>
          : (
            <span className={`t-${originTone(provenance.origin)}`}>
              {provenance.origin}
            </span>
          )}
      />
      {provenance.originWhy && (
        <p className="loom-note">Origin unresolved: {provenance.originWhy}.</p>
      )}
      <Kv label="artifact" value={<code>{provenance.artifactKind}</code>} />
      <Kv
        label="read at"
        value={<code className="loom-ref-path">{provenance.artifactRef}</code>}
      />
      <Kv label="revision" value={
        provenance.revisionId
          ? <code>{provenance.revisionId}</code>
          : <span className="muted">—</span>
      } mono />
      <p className="loom-note">{provenance.revisionWhy}.</p>
      <Freshness provenance={provenance} />
      {provenance.runId && (
        <Kv label="run" value={<code>{provenance.runId}</code>} />
      )}
      {!resolved.present && (
        <p className="loom-note warn" role="status">
          Not resolvable on this revision — {resolved.why}. The id is kept and
          the reason is stated; nothing is drawn in its place.
        </p>
      )}
    </>
  );
}

function Chip({ id, store, data, view }: {
  id: LoomId;
  store: LoomSelectionStore;
  data: LoomData;
  view: LoomViewId;
}): ReactElement {
  const provenance = provenanceOf(id, data);
  const carried = carriedKinds(view).includes(id.kind);
  const home = PRIMARY_VIEW[id.kind];
  const resolved = resolveAgainstData(id, data);
  return (
    <li
      className={`loom-selchip${carried ? '' : ' elsewhere'}`}
      title={`${provenance.noun} · ${provenance.artifactRef}`}
    >
      <button
        type="button"
        className="loom-selchip-main"
        title="Hold only this object"
        onClick={() => store.select(id)}
      >
        <span className={`loom-origin t-${originTone(provenance.origin)}`}>
          {provenance.origin ?? 'ORIGIN ?'}
        </span>
        <code>{loomIdText(id)}</code>
      </button>
      <span className="loom-selchip-meta">
        {provenance.noun}
        {' · '}
        {carried ? (
          <span className={`t-${freshnessTone(provenance.freshness.state)}`}>
            {provenance.freshness.state}
          </span>
        ) : (
          <Link className="link" to={store.href(home)}>
            open in {home} →
          </Link>
        )}
        {!resolved.present && ' · not on this revision'}
      </span>
      <button
        type="button"
        className="loom-selchip-x"
        aria-label={`Remove ${loomIdText(id)} from the selection`}
        onClick={() => store.drop(id)}
      >
        ×
      </button>
    </li>
  );
}

export default function SelectionBar({ store, data, view, carried }: {
  store: LoomSelectionStore;
  data: LoomData;
  view: LoomViewId;
  /** How many of the selected ids this view can actually render. */
  carried: number;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const share = useRef<HTMLInputElement | null>(null);
  const ids = selectionIds(store.selection);
  // Resolved once per render rather than per use: an origin lookup walks the
  // served vocabulary, and the chip and the panel must not be able to disagree.
  const held = ids.map((id) => ({ id, provenance: provenanceOf(id, data) }));

  const summary: ReactNode = ids.length === 0
    ? <span className="muted">nothing selected</span>
    : (
      <ul className="loom-selchips">
        {ids.map((id) => (
          <Chip key={loomIdText(id)} id={id} store={store} data={data} view={view} />
        ))}
      </ul>
    );

  return (
    <div className={`loom-selbar${ids.length === 0 ? ' is-empty' : ''}`}>
      {ids.length === 0 ? (
        <p className="loom-selection-empty">Select an item to inspect its source and revision.</p>
      ) : (
        <>
          <div className="loom-selbar-head">
            <span className="context-label">SELECTION</span>
            <span className="loom-selcount">
              {ids.length} id{ids.length === 1 ? '' : 's'}
              {store.selection.mode === 'graph'
                ? ' · graph set'
                : store.selection.mode === 'record' ? ' · single record' : ''}
            </span>
            {carried !== ids.length && (
              <span className="loom-selcarry">
                {carried} of {ids.length} carried by this tab
              </span>
            )}
            <div className="loom-selbar-actions">
              <button type="button" className="btn"
                onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                Provenance
              </button>
              <button type="button" className="btn" onClick={() => {
                store.copy();
                if (!navigator.clipboard) share.current?.select();
              }}>
                {store.copied ? 'Link copied' : 'Copy link'}
              </button>
              <button type="button" className="btn" onClick={store.clear}>Clear</button>
            </div>
          </div>
          {summary}
          <input
            ref={share}
            className="loom-share"
            type="text"
            readOnly
            value={store.shareUrl}
            aria-label="Link that reproduces this view and selection"
            title={store.shareUrl}
            onFocus={(e) => e.currentTarget.select()}
          />
        </>
      )}

      {open && ids.length > 0 && (
        <div className="loom-provenance">
          {held.map(({ id, provenance }) => (
            <section key={loomIdText(id)} className="loom-provenance-item">
              <h4>
                <code>{loomIdText(id)}</code>
                <span className="muted">{provenance.noun}</span>
              </h4>
              <Provenance provenance={provenance} data={data} />
            </section>
          ))}
          <p className="loom-hint">
            Origins are resolved from the provenance vocabulary the gateway
            serves, and freshness for anything measured is the server's own
            verdict on the run. Neither is decided here. The vocabulary read is{' '}
            {data.provenance.result.state === 'ready'
              ? 'in place'
              : data.provenance.result.state === 'error'
                ? 'UNREADABLE — every origin below is unresolved'
                : 'still in flight'}.
          </p>
        </div>
      )}

      {store.rejected.length > 0 && (
        <div className="loom-ext is-bad" role="note">
          <div className="loom-ext-title">
            This address names {store.rejected.length} object(s) the selection does not hold
          </div>
          <p className="loom-ext-body">
            Each line says why. Nothing was resolved to a nearby object in their
            place, and the address has not been rewritten — fix it here or leave
            it, but read it as narrower than it looks.
          </p>
          <ul className="loom-refs">
            {store.rejected.map((r, i) => (
              <li key={`${r.text}-${i}`}>
                <code>{r.text}</code> — {r.why}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}