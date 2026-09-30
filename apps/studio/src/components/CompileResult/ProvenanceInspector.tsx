import { useState, type ReactElement } from 'react';
import type { ArtifactChainView, ProvenanceGroup } from '../../api';
import { Hash, humanize } from '../badges';
import { Link } from '../../studio';
import ArtifactChain from '../ArtifactChain';

const ARTIFACT_JUMPS: { match: RegExp; tab: string; label: string }[] = [
  { match: /topology/i, tab: 'fabric', label: 'Fabric' },
  { match: /route/i, tab: 'routing', label: 'Routing' },
  { match: /vc_assignment|vc/i, tab: 'resources', label: 'Resources' },
  { match: /address/i, tab: 'address_decode', label: 'Address Decode' },
  { match: /mapping/i, tab: 'mapping', label: 'Mapping' },
];

function jumpFor(artifact: string): { tab: string; label: string } | null {
  if (/certificate/i.test(artifact)) return null;
  for (const j of ARTIFACT_JUMPS) {
    if (j.match.test(artifact)) return j;
  }
  return null;
}

export default function ProvenanceInspector({ group, projectId, onJump }: {
  group: ProvenanceGroup;
  projectId: string;
  onJump: (tab: string) => void;
}): ReactElement {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, value: string | null): Promise<void> => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    } catch {
    }
  };
  const hashes = Object.entries(group.artifact_hashes ?? {});
  return (
    <section className="card">
      <h4>Provenance</h4>
      <div className="kv"><span>design identity</span>
        <Hash value={group.design_hash} />
        <button className="btn btn-small"
                onClick={() => void copy('design', group.design_hash)}>
          {copied === 'design' ? 'copied' : 'copy full hash'}
        </button></div>
      <div className="kv"><span>resolved fabric</span>
        <Hash value={group.resolved_fabric_hash} />
        <button className="btn btn-small"
                onClick={() => void copy('fabric', group.resolved_fabric_hash)}>
          {copied === 'fabric' ? 'copied' : 'copy full hash'}
        </button></div>
      <div className="kv"><span>certificate</span>
        <Hash value={group.certificate_id} />
        <button className="btn btn-small"
                onClick={() => void copy('cert', group.certificate_id)}>
          {copied === 'cert' ? 'copied' : 'copy full hash'}
        </button></div>
      <div className="kv"><span>compiler semantics</span>
        <span>v{group.compiler_semantics_version ?? '—'}</span></div>
      {group.artifact_chain && (
        <>
          <h5 className="inspector-label">Artifact chain</h5>
          <ChainWithJumps chain={group.artifact_chain} projectId={projectId}
                          onJump={onJump} copy={copy} copied={copied} />
        </>
      )}
      <details>
        <summary>artifact hashes ({hashes.length})</summary>
        {hashes.length === 0 ? (
          <p className="muted">No artifact hashes were recorded.</p>
        ) : (
          <table className="tbl">
            <tbody>
              {hashes.map(([key, value]) => {
                const jump = jumpFor(key);
                return (
                  <tr key={key}>
                    <td className="muted">{humanize(key)}</td>
                    <td><Hash value={value} /></td>
                    <td>
                      <button className="btn btn-small"
                              onClick={() => void copy(key, value)}>
                        {copied === key ? 'copied' : 'copy'}
                      </button>{' '}
                      {jump ? (
                        <button className="btn btn-small"
                                onClick={() => onJump(jump.tab)}>
                          → {jump.label}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </details>
    </section>
  );
}

function ChainWithJumps({ chain, projectId, onJump, copy, copied }: {
  chain: ArtifactChainView;
  projectId: string;
  onJump: (tab: string) => void;
  copy: (key: string, value: string | null) => Promise<void>;
  copied: string | null;
}): ReactElement {
  return (
    <>
      <ArtifactChain chain={chain} />
      <ArtifactNodeActions chain={chain} projectId={projectId}
                           onJump={onJump} copy={copy} copied={copied} />
    </>
  );
}

function ArtifactNodeActions({ chain, projectId, onJump, copy, copied }: {
  chain: ArtifactChainView;
  projectId: string;
  onJump: (tab: string) => void;
  copy: (key: string, value: string | null) => Promise<void>;
  copied: string | null;
}): ReactElement {
  const [open, setOpen] = useState<string | null>(null);
  const byId = new Map(chain.nodes.map((n) => [n.artifact, n]));
  return (
    <div className="artifact-jumps">
      <label>artifact detail
        <select value={open ?? ''}
                onChange={(e) => setOpen(e.target.value || null)}
                aria-label="Select artifact for detail">
          <option value="">select…</option>
          {chain.nodes.map((n) => (
            <option key={n.artifact} value={n.artifact}>{n.label}</option>
          ))}
        </select>
      </label>
      {open && byId.get(open) && (
        <div className="inspector-detail">
          {(() => {
            const node = byId.get(open);
            if (!node) return null;
            const jump = jumpFor(node.artifact);
            const isCert = /certificate/i.test(node.artifact);
            return (
              <>
                <div className="kv"><span>identity</span>
                  <Hash value={node.hash} />
                  <button className="btn btn-small"
                          onClick={() => void copy(node.artifact, node.hash)}>
                    {copied === node.artifact ? 'copied' : 'copy full hash'}
                  </button></div>
                <div className="kv"><span>derived from</span>
                  <span>{node.parents.length === 0
                    ? 'user intent (no parents)'
                    : node.parents.map(
                      (p) => byId.get(p)?.label ?? p).join(' + ')}</span></div>
                <div className="kv"><span>proved by</span>
                  <span>{node.proved_by.length > 0
                    ? node.proved_by.join(', ') : '—'}</span></div>
                <div className="form-row">
                  {jump && (
                    <button className="btn btn-small"
                            onClick={() => onJump(jump.tab)}>
                      → {jump.label}
                    </button>
                  )}
                  {isCert && (
                    <Link className="btn btn-small"
                          to={`/projects/${projectId}/verify`}>
                      → Verify
                    </Link>
                  )}
                </div>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
