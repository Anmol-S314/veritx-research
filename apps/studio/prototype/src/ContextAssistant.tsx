import { useEffect, useMemo, useRef, useState } from 'react';
import { gateway, gatewayReason, type SimLoad, type Topology } from './gateway';
import { pageFromHash } from './model';
import { useProject, type LoadedProject, type LoadedRun } from './project';
import { useRunTopology } from './runTopology';
import { useSimLoad } from './measuredData';
import { portWiresUsable, usePortWires } from './portWires';
import { Icon } from './ui';
import {
  attachPick, clearPicks, closeAssistant, findContextTarget, flashContextTarget, isPickingContext, openAssistant,
  removePick, startPicking, stopPicking, useAssistantContext,
} from './contextSelection';
import {
  answerLocally, buildContextPacket, contextPacketSize, packetSummary, suggestedQuestions,
  type ContextPacket, type LocalAnswer,
} from './assistantContext';
import { resolveContextSelection, type ContextSelection } from './contextSelection';

type Message = { role: 'user' | 'assistant'; text: string; answer?: LocalAnswer };

function useRoute() {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const page = pageFromHash(hash);
  return { route: hash.replace(/^#\/?/, '') || 'design/system', page };
}

function useKeyboardShortcut() {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if (typing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'i') {
        event.preventDefault();
        if (isPickingContext()) stopPicking(); else startPicking();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

export function ContextAssistant() {
  useKeyboardShortcut();
  const ui = useAssistantContext();
  const { project, run } = useProject();
  const loadedProject = project.phase === 'loaded' ? project.data : null;
  const loadedRun = run.phase === 'loaded' ? run.data : null;
  if (!ui.open) return <AssistantLauncher />;
  if (loadedProject && loadedRun) return <LiveAssistant project={loadedProject} run={loadedRun} />;
  return <AssistantPanel project={loadedProject} run={null} topology={loadedProject?.topology ?? null} load={null} />;
}

function AssistantLauncher() {
  return <button type="button" className="assistant-launch" data-context-ignore onClick={openAssistant} aria-label="Open contextual assistant">
    <Icon name="assistant" size={15} />
    <span>Ask about this</span>
  </button>;
}

function LiveAssistant({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const topology = useRunTopology(project, run);
  const loadState = useSimLoad(run.detail.run_id);
  const wireState = usePortWires(run, topology);
  return <AssistantPanel
    project={project}
    run={run}
    topology={topology}
    load={loadState.phase === 'ready' ? loadState.data ?? null : null}
    loadReason={loadState.phase === 'absent' ? loadState.reason ?? null : loadState.phase === 'error' ? loadState.reason ?? null : null}
    portWires={portWiresUsable(wireState.map) ? wireState.map.ports : undefined}
    wireReason={topology && (topology.shared_links?.length ?? 0) > 0 && (wireState.phase === 'invalid' || wireState.phase === 'absent') ? wireState.reason ?? null : null}
  />;
}

type AssistantPanelProps = {
  project: LoadedProject | null;
  run: LoadedRun | null;
  topology: Topology | null;
  load: SimLoad | null;
  loadReason?: string | null;
  portWires?: Map<string, { wire: number; taps: number[] }>;
  wireReason?: string | null;
};

function AssistantPanel({ project, run, topology, load, loadReason = null, portWires, wireReason = null }: AssistantPanelProps) {
  const ui = useAssistantContext();
  const { route, page } = useRoute();
  const [mode, setMode] = useState<'local' | 'model'>('local');
  const [includeDraft, setIncludeDraft] = useState(false);
  const [preview, setPreview] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState('');
  const [agent, setAgent] = useState<{ phase: 'idle' | 'loading' | 'ready' | 'error'; configured?: boolean; reason?: string; model?: string | null }>({ phase: 'idle' });
  const bodyRef = useRef<HTMLDivElement>(null);

  const scopeKey = `${project?.detail.project.project_id ?? 'sample'}:${run?.detail.run_id ?? 'no-run'}`;
  useEffect(() => { clearPicks(); setMessages([]); setError(''); setConsent(false); }, [scopeKey]);

  useEffect(() => {
    if (!ui.open || ui.picking) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') closeAssistant(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [ui.open, ui.picking]);

  useEffect(() => {
    if (!ui.open) return;
    let live = true;
    setAgent(current => current.phase === 'ready' ? current : { phase: 'loading' });
    gateway.agentCapabilities()
      .then(data => { if (live) setAgent({ phase: 'ready', configured: Boolean(data.configured), reason: data.reason, model: data.model }); })
      .catch(reason => { if (live) setAgent({ phase: 'error', configured: false, reason: gatewayReason(reason) }); });
    return () => { live = false; };
  }, [ui.open]);

  const packet = useMemo(() => buildContextPacket({
    route,
    page: page ? { title: page.title, group: page.group } : null,
    project,
    run,
    topology,
    load,
    portWires,
    picks: ui.picks,
    includeDraft,
  }), [route, page, project, run, topology, load, portWires, ui.picks, includeDraft]);

  const suggestions = useMemo(() => suggestedQuestions(packet), [packet]);
  const packetBytes = useMemo(() => contextPacketSize(packet), [packet]);
  const tooLarge = packetBytes > 64 * 1024;
  const modelReady = agent.phase === 'ready' && agent.configured === true;

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [preview, mode]);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    if (mode === 'model') {
      if (!modelReady) { setError(agent.reason || 'No model runtime is configured, so the context pack cannot be sent.'); return; }
      if (!project) { setError('Model-assisted context needs a loaded gateway project.'); return; }
      if (!consent) { setError('Explicit consent is required before sending this context pack to the configured model.'); return; }
    }
    setBusy(true); setError('');
    const history = messages.slice(-20).map(message => ({ role: message.role, content: message.text }));
    try {
      if (mode === 'model' && project) {
        const response = await gateway.agentChat(project.detail.project.project_id, {
          message: text,
          history,
          allowModel: true,
          includeDraft: false,
          context: packet,
        });
        setMessages(rows => [...rows, { role: 'user', text }, { role: 'assistant', text: String(response.text ?? 'No response text was returned.') }]);
        setConsent(false);
      } else {
        const answer = answerLocally(text, packet);
        setMessages(rows => [...rows, { role: 'user', text }, { role: 'assistant', text: answer.paragraphs.join('\n\n'), answer }]);
      }
      setInput('');
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setBusy(false);
    }
  };

  const close = () => closeAssistant();
  const pageLabel = page?.title ?? 'Current view';
  const projectLabel = project?.detail.project.name ?? 'Sample project';
  const revision = project?.detail.active_revision_id ?? run?.detail.revision_id ?? null;
  const runId = run?.detail.run_id ?? null;

  return <>
    <PickerLayer />
    <aside className={`assistant-drawer${ui.open && !ui.picking ? ' open' : ''}`} aria-label="Contextual assistant" aria-hidden={!ui.open || ui.picking} data-context-ignore>
      <header className="assistant-header">
        <div className="assistant-title">
          <span className="assistant-mark"><Icon name="assistant" size={14} /></span>
          <h2>Contextual assistant</h2>
          <span className="badge blue">Read-only</span>
        </div>
        <div className="assistant-modes" role="group" aria-label="Assistant mode">
          <button type="button" className={mode === 'local' ? 'active' : ''} aria-pressed={mode === 'local'} onClick={() => { setMode('local'); setError(''); }}>Local</button>
          <button type="button" className={mode === 'model' ? 'active' : ''} aria-pressed={mode === 'model'} onClick={() => { setMode('model'); setError(''); }}>Model-assisted</button>
        </div>
        <button type="button" className="icon-button" aria-label="Close contextual assistant" onClick={close}><Icon name="close" size={14} /></button>
      </header>

      <div className="assistant-context">
        <div className="context-chips">
          <span className="context-chip"><b>{projectLabel}</b></span>
          {revision && <span className="context-chip mono">{revision}</span>}
          {runId && <span className="context-chip mono">{runId}</span>}
          <span className="context-chip">{pageLabel}</span>
          {ui.picks.map(pick => <span className="context-chip accent" key={`${pick.kind}:${pick.id}`} onMouseEnter={() => flashContextTarget(pick.kind, pick.id)}>
            <button type="button" className="chip-jump" title={`Show ${pick.label} on the page`} onClick={() => findContextTarget(pick.kind, pick.id)?.scrollIntoView({ block: 'center', behavior: 'smooth' })}><b>{pick.label}</b></button>
            <button type="button" className="chip-remove" aria-label={`Remove ${pick.label} from context`} onClick={() => removePick(pick.kind, pick.id)}><Icon name="close" size={9} /></button>
          </span>)}
        </div>
        <div className="context-actions">
          <button type="button" className="text-button" onClick={startPicking}><Icon name="target" size={11} /> Pick context</button>
          <button type="button" className="text-button" onClick={() => setPreview(value => !value)} aria-expanded={preview}>{preview ? 'Hide context' : 'Preview context'}</button>
          {ui.picks.length > 0 && <button type="button" className="text-button" onClick={clearPicks}>Clear picks</button>}
          <span className="context-note">{packetBytes.toLocaleString()} B · nothing sent until you ask</span>
        </div>
      </div>

      <div className="assistant-body" ref={bodyRef}>
        {mode === 'model' && <div className={`mode-note${modelReady ? ' ready' : ''}`}>
          <strong>{modelReady ? 'Model-assisted.' : 'Model-assisted unavailable.'}</strong>{' '}
          {modelReady ? (tooLarge ? `The context pack is ${packetBytes.toLocaleString()} B, above the gateway's 64 KiB limit. Uncheck Draft snapshot or clear a pick before sending.` : `The exact context pack below is sent to ${agent.model ?? 'the configured runtime'} after consent; the model gets no tools and cannot change the draft.`) : agent.phase === 'loading' ? 'Checking the configured runtime…' : agent.reason || 'No model provider is configured on the gateway.'}
        </div>}
        {preview && <ContextPack packet={packet} />}

        <section className="assistant-suggested" aria-label="Suggested questions">
          <div className="suggested-head"><h3>Suggested for this context</h3><span>{ui.picks.length ? 'from the pick' : 'from the view'}</span></div>
          <div className="suggested-grid">
            {suggestions.map(question => <button type="button" key={question} onClick={() => mode === 'local' ? void ask(question) : setInput(question)}>{question}</button>)}
            <button type="button" className="wide" onClick={() => void ask('What is missing from this evidence?')}>What is missing from this evidence?</button>
          </div>
        </section>

        <div className="assistant-thread" aria-live="polite">
          {messages.map((message, index) => <div className={`assistant-message ${message.role}`} key={`${index}-${message.role}`}>
            {message.role === 'user' ? <div className="assistant-bubble">{message.text}</div> : <div className="assistant-answer">
              {message.answer ? <>
                {message.answer.paragraphs.map((paragraph, part) => <p key={part}>{paragraph}</p>)}
                {message.answer.evidence.length > 0 && <div className="answer-evidence">{message.answer.evidence.map(item => <span key={`${item.label}:${item.value}`}><b>{item.value}</b> {item.label}</span>)}</div>}
                {message.answer.caveats.map((caveat, part) => <p className="assistant-caveat" key={`caveat-${part}`}><b>Not established:</b> {caveat}</p>)}
              </> : <p>{message.text}</p>}
            </div>}
          </div>)}
          {busy && <p className="assistant-thinking">{mode === 'model' ? 'Waiting for the configured runtime…' : 'Reading the attached context…'}</p>}
        </div>

        {error && <div className="assistant-error" role="alert">{error}</div>}
        {loadReason && <p className="assistant-gap"><b>Measured series unavailable:</b> {loadReason}</p>}
        {wireReason && <p className="assistant-gap"><b>Wire join unavailable:</b> {wireReason}</p>}
      </div>

      <div className="assistant-composer">
        <div className="assistant-composer-box">
          <textarea rows={2} maxLength={16000} value={input} disabled={busy} placeholder={mode === 'model' ? 'Ask about this context (model-assisted)…' : 'Ask about this context…'} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void ask(input); } }} />
          <div className="assistant-composer-row">
            <label className="check-row compact"><input type="checkbox" checked={includeDraft} disabled={!project?.request} onChange={event => setIncludeDraft(event.target.checked)} />Draft snapshot</label>
            {mode === 'model' && <label className="check-row compact"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />Allow this context pack to be sent</label>}
            {mode === 'model' && tooLarge && <span className="assistant-gap-inline">Context exceeds 64 KiB</span>}
            <span className="spacer" />
            <button type="button" className="button primary" disabled={!input.trim() || busy || (mode === 'model' && (!modelReady || !consent || !project || tooLarge))} onClick={() => void ask(input)}>{busy ? 'Working…' : mode === 'model' ? 'Send to model' : 'Explain locally'}</button>
          </div>
        </div>
        <div className="assistant-composer-note">
          <span>{packetSummary(packet)}</span>
        </div>
      </div>
    </aside>
  </>;
}

function ContextPack({ packet }: { packet: ContextPacket }) {
  return <section className="assistant-context-pack">
    <div className="context-pack-head"><h3>Context pack</h3><span>{packetSummary(packet)}</span></div>
    <dl className="context-pack-props">
      <div><dt>Project</dt><dd>{packet.scope.project?.name ?? 'None loaded'}</dd></div>
      <div><dt>Revision</dt><dd className="mono">{packet.scope.revision ?? '—'}</dd></div>
      <div><dt>Run</dt><dd>{packet.scope.run ? `${packet.scope.run.id} · ${packet.scope.run.status ?? 'unknown'}` : 'None'}</dd></div>
      <div><dt>Topology</dt><dd>{packet.scope.topology ? `${packet.scope.topology.family} · ${packet.scope.topology.routers} routers` : 'Not loaded'}</dd></div>
      <div><dt>Measured</dt><dd>{packet.measured ? `${packet.measured.channels} channels · ${packet.measured.active_channels} active` : 'Not loaded'}</dd></div>
      <div><dt>Selections</dt><dd>{packet.selections.length}</dd></div>
      <div><dt>Draft</dt><dd>{packet.draft ? 'Included' : 'Not included'}</dd></div>
    </dl>
    <pre className="code-preview assistant-context-json">{JSON.stringify(packet, null, 2)}</pre>
  </section>;
}

export function PickerLayer() {
  const { picking, picks } = useAssistantContext();
  const [hover, setHover] = useState<{ selection: ContextSelection; rect: DOMRect } | null>(null);
  const hoveredRef = useRef<ContextSelection | null>(null);
  const pickingRef = useRef(picking);
  pickingRef.current = picking;

  useEffect(() => {
    if (!picking) { setHover(null); hoveredRef.current = null; return; }
    document.body.classList.add('context-picking');
    const measure = (selection: ContextSelection | null) => {
      hoveredRef.current = selection;
      if (!selection) { setHover(null); return; }
      const rect = selection.element.getBoundingClientRect();
      setHover({ selection, rect });
    };
    const move = (event: PointerEvent) => {
      if (!pickingRef.current) return;
      measure(resolveContextSelection(event.target as Element));
    };
    const click = (event: MouseEvent) => {
      if (!pickingRef.current) return;
      const target = event.target as Element | null;
      if (target?.closest('[data-context-ignore]')) return;
      const selection = resolveContextSelection(target);
      if (!selection) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      const keepPicking = event.shiftKey;
      attachPick(selection.pick, { keepPicking });
      window.setTimeout(() => flashContextTarget(selection.pick.kind, selection.pick.id), 40);
      if (!keepPicking) setHover(null);
    };
    const key = (event: KeyboardEvent) => {
      if (!pickingRef.current) return;
      if (event.key === 'Escape') { event.preventDefault(); stopPicking(); return; }
      if (event.key === 'Enter' || event.key === ' ') {
        const selection = resolveContextSelection(document.activeElement);
        if (selection) { event.preventDefault(); const keepPicking = event.shiftKey; attachPick(selection.pick, { keepPicking }); if (!keepPicking) setHover(null); }
      }
    };
    const scroll = () => measure(hoveredRef.current);
    document.addEventListener('pointermove', move, true);
    document.addEventListener('click', click, true);
    document.addEventListener('keydown', key, true);
    window.addEventListener('scroll', scroll, true);
    window.addEventListener('resize', scroll);
    return () => {
      document.body.classList.remove('context-picking');
      document.removeEventListener('pointermove', move, true);
      document.removeEventListener('click', click, true);
      document.removeEventListener('keydown', key, true);
      window.removeEventListener('scroll', scroll, true);
      window.removeEventListener('resize', scroll);
    };
  }, [picking]);

  useEffect(() => {
    if (!picking) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') stopPicking(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [picking]);

  if (!picking) return null;
  return <>
    {hover && <div className="context-pick-outline" style={{ left: hover.rect.left, top: hover.rect.top, width: hover.rect.width, height: hover.rect.height }}>
      <span className="context-pick-label">{hover.selection.pick.kind === 'router' || hover.selection.pick.kind === 'channel' || hover.selection.pick.kind === 'wire' ? '' : 'Context · '}{hover.selection.pick.label}</span>
    </div>}
    <div className="context-pick-toast" role="status" data-context-ignore>
      <Icon name="target" size={14} />
      <span><b>Pick context.</b> {hover ? `Selected: ${hover.selection.pick.label}.` : 'Move over the application to inspect.'} {picks.length ? `${picks.length} attached. Shift-click adds another; Esc finishes.` : 'Click any object, row, card, chart mark, or section.'}</span>
      <button type="button" className="button" onClick={stopPicking}>{picks.length ? 'Done' : 'Cancel'} <kbd>Esc</kbd></button>
    </div>
  </>;
}
