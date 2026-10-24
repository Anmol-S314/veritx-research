import { useState } from 'react';
import { gateway } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { Button, Empty, Field, Notice, Section, downloadJson } from './ui';

export function EvidenceDocuments({ runId }: { runId: string }) {
  const { data, error } = useGatewayDocument(`evidence-documents:${runId}`, () => gateway.runEvidence(runId));
  const [selection, setSelection] = useState(''), [query, setQuery] = useState('');
  const documents = data?.documents ?? {}, paths = Object.keys(documents).filter(p => p.toLowerCase().includes(query.toLowerCase()));
  const selected = paths.includes(selection) ? selection : paths[0];
  return <Section title="Evidence document inspector">
    {error ? <Notice tone="red">{error}</Notice> : !data ? <p>Reading evidence…</p> : <>
      <div className="toolbar"><Field label="Filter evidence documents"><input value={query} onChange={e => setQuery(e.target.value)} /></Field><Field label="Evidence document"><select value={selected ?? ''} onChange={e => setSelection(e.target.value)}>{paths.map(path => <option key={path}>{path}</option>)}</select></Field></div>
      {selected ? <><Button onClick={() => downloadJson(selected.split('/').pop() ?? 'evidence.json', documents[selected])}>Download selected JSON document</Button><pre className="code-preview">{JSON.stringify(documents[selected], null, 2)}</pre><p>JSON is reserialized for download. Manifest digests describe the original file bytes.</p></> : <Empty title="No matching documents">Only documents returned by the evidence API are available here.</Empty>}
      <details><summary>Artifact sizes and producer identity</summary><pre className="code-preview">{JSON.stringify({ producer: data.producer, artifacts: data.artifacts }, null, 2)}</pre></details>
    </>}
  </Section>;
}
