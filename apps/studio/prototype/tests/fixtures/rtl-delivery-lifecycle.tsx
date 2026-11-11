import { useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { FinalDelivery } from '../../src/FinalDelivery';
import type { LoadedProject } from '../../src/project';
import '../../src/styles.css';

function Fixture() {
  const [id, setId] = useState(new URLSearchParams(location.search).get('project_id') ?? 'p-rtl-delivery');
  const [revision, setRevision] = useState(1);
  const previousScope = useRef(`${id}:${revision}`);
  const leaks = useRef<string[]>([]);
  const log = useRef<HTMLOutputElement>(null);
  const project: LoadedProject = {
    detail: {
      project: { project_id: id, name: id, created_at: '2026-11-08', updated_at: '2026-11-08' },
      active_revision_id: `${id}-r${revision}`, active_revision: null, runs: [],
    },
    request: null, draftMeta: { revisionToken: `${id}-draft-${revision}` },
    topology: null, topologyError: '', compileResult: null, compileResultError: '',
  };
  useLayoutEffect(() => {
    const scope = `${id}:${revision}`;
    if (previousScope.current !== scope) {
      // Inspect the committed transition DOM before passive reset effects can hide a leak.
      const section = document.querySelectorAll('#delivery-harness section.section')[1];
      if (section?.querySelector('a[href*="/rtl-previews/"]') || section?.textContent?.includes('This preview was generated from a different draft')) {
        leaks.current.push(scope);
      }
      previousScope.current = scope;
    }
    if (log.current) log.current.textContent = JSON.stringify(leaks.current);
  }, [id, revision]);
  return <main>
    <button onClick={() => setId('p-second')}>Switch project</button>
    <button onClick={() => setRevision(value => value + 1)}>Switch revision</button>
    <output ref={log} data-testid="scope-leaks">[]</output>
    <div id="delivery-harness"><FinalDelivery project={project} /></div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<Fixture />);
