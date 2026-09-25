import { useState, type ReactElement } from 'react';
import type { CompilationView } from '../types';
import { Hash, shortHash } from './badges';

interface Artifact {
  key: string;
  label: string;
  value: string | undefined;
}

/** Canonical artifact strip (SROTA template): topology -> attachment ->
 * route -> VC -> resolved fabric, each bound to its live compiler hash.
 * Only real artifacts are shown; a missing hash is a disabled chip. */
export default function ArtifactStrip({
  compilation,
}: {
  compilation: CompilationView | null;
}): ReactElement {
  const [selected, setSelected] = useState('resolved_fabric_hash');
  const hashes = compilation?.artifact_hashes ?? {};
  const artifacts: Artifact[] = [
    { key: 'topology_hash', label: 'Topology', value: hashes['topology_hash'] },
    { key: 'attachment_hash', label: 'Attachment', value: hashes['attachment_hash'] },
    { key: 'router_route_hash', label: 'Route', value: hashes['router_route_hash'] },
    { key: 'vc_assignment_hash', label: 'VC assignment', value: hashes['vc_assignment_hash'] },
    {
      key: 'resolved_fabric_hash',
      label: 'Resolved fabric',
      value: compilation?.resolved_fabric_hash
        ?? hashes['resolved_fabric_hash'],
    },
  ];
  const active = artifacts.find((a) => a.key === selected);

  return (
    <div className="artifact-strip-wrap">
      <div className="artifact-strip" role="tablist" aria-label="Canonical artifacts">
        {artifacts.map((artifact) => (
          <button
            key={artifact.key}
            role="tab"
            aria-selected={selected === artifact.key}
            className={`artifact${selected === artifact.key ? ' active' : ''}`}
            disabled={!artifact.value}
            title={artifact.value ?? 'artifact not present'}
            onClick={() => setSelected(artifact.key)}
          >
            <span>{artifact.label}</span>
            <code>{artifact.value ? shortHash(artifact.value) : 'not present'}</code>
          </button>
        ))}
      </div>
      {active?.value && (
        <div className="artifact-detail">
          <span className="ctx-key">{active.label}</span>
          <Hash value={active.value} />
        </div>
      )}
    </div>
  );
}
