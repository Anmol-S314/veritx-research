import { useState } from 'react';
import { gateway } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { bytes as formatBytes, withoutIdentity } from './format';
import { Badge, Button, CodePanel, CopyButton, Empty, Field, Icon, Notice, Section, downloadJson } from './ui';

export function EvidenceDocuments({ runId }: { runId: string }) {
  const { data, error } = useGatewayDocument(`evidence-documents:${runId}`, () => gateway.runEvidence(runId));
  const [selection, setSelection] = useState(''), [query, setQuery] = useState('');
  const allDocuments = data?.documents ?? {};
  const paths = Object.keys(allDocuments).filter(p => p.toLowerCase().includes(query.toLowerCase()));
  const selected = paths.includes(selection) ? selection : paths[0];
  const preview = selected ? JSON.stringify(withoutIdentity(allDocuments[selected]), null, 2) : '';
  const previewBytes = new TextEncoder().encode(preview).length;
  return <Section title="Evidence document inspector" actions={<Badge>{paths.length} of {Object.keys(allDocuments).length} documents</Badge>}>
    {error ? <Notice tone="red">{error}</Notice> : !data ? <p>Reading evidence…</p> : <>
      <div className="toolbar evidence-toolbar">
        <Field label="Filter evidence documents"><input aria-label="Filter evidence documents" placeholder="Filter by path…" value={query} onChange={e => setQuery(e.target.value)} /></Field>
        <Field label="Evidence document"><select aria-label="Evidence document" value={selected ?? ''} onChange={e => setSelection(e.target.value)}>{paths.map(path => <option key={path}>{path}</option>)}</select></Field>
      </div>
      {selected ? <>
        <CodePanel title={<><span className="mono">{selected}</span><small>{preview.split('\n').length.toLocaleString()} lines · {formatBytes(previewBytes)} preview</small></>} actions={<><CopyButton text={preview} label="Copy JSON" /><Button onClick={() => downloadJson(selected.split('/').pop() ?? 'evidence.json', allDocuments[selected])}><Icon name="download" size={13} />Download</Button></>}>
          {preview}
        </CodePanel>
        <p className="meta-line">JSON is reserialized for this preview. Content identities are omitted here; the downloaded document retains the original fields.</p>
      </> : <Empty icon="file" title="No matching documents">Only documents returned by the evidence API are available here. Clear the filter to see the rest.</Empty>}
      <details><summary>Artifact sizes and producer identity</summary><pre className="code-preview">{JSON.stringify(withoutIdentity({ producer: data.producer, artifacts: data.artifacts }), null, 2)}</pre></details>
    </>}
  </Section>;
}
