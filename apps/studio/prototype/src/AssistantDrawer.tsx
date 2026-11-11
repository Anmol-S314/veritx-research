import { useEffect, useMemo, useState } from 'react';
import { answerFreeText, answerQuestion, buildAssistantContext, suggestedQuestions, type AssistantAction, type AssistantAnswer, type AssistantQuestion } from './assistant';
import { useChannelSelection, revealChannelDetail } from './channelSelection';
import { GATEWAY_START, gateway, gatewayReason } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { useSimLoad } from './measuredData';
import type { LoadedProject, LoadedRun } from './project';
import type { PageId } from './model';
import { Badge, Button, Dialog, Field, Icon, Notice } from './ui';
import { PickerLayer } from './ContextAssistant';
import { clearPicks, findContextTarget, flashContextTarget, isPickingContext, removePick, startPicking, stopPicking, useAssistantContext } from './contextSelection';
import { answerLocally, buildContextPacket, contextPacketSize, suggestedQuestions as pickedSuggestions, type LocalAnswer } from './assistantContext';

type Message =
  | { role: 'user'; text: string }
  | { role: 'assistant'; answer: AssistantAnswer; source: 'local' | 'model' };

type AssistantDrawerProps = {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  page: { id: string; title: string; short: string; group: string } | null;
  project: LoadedProject | null;
  run: LoadedRun | null;
  navigate: (page: PageId) => void;
};

const shortRun = (id?: string | null) => id ? `${id.slice(0, 13)}…` : 'no run';

const toAssistantAnswer = (answer: LocalAnswer): AssistantAnswer => ({
  paragraphs: answer.paragraphs,
  evidence: answer.evidence,
  actions: [],
  caveat: answer.caveats.join(' '),
});

function AnswerView({ answer, source, onAction }: { answer: AssistantAnswer; source: 'local' | 'model'; onAction: (action: AssistantAction) => void }) {
  return <div className="assistant-answer">
    <div className="assistant-answer-kicker">{source === 'model' ? 'Model suggestion · not evidence' : 'Local explainer · from this context'}</div>
    {answer.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
    {answer.evidence.length > 0 && <div className="assistant-evidence">
      {answer.evidence.map(item => <span key={`${item.label}:${item.value}`}><small>{item.label}</small>{item.value}</span>)}
    </div>}
    {answer.actions.length > 0 && <div className="assistant-actions">
      {answer.actions.map((action, index) => <button key={`${action.label}:${index}`} type="button" className={`button assistant-action${index === 0 ? ' primary' : ''}`} onClick={() => onAction(action)}>{action.label}</button>)}
    </div>}
    {answer.caveat && <p className="assistant-caveat">{answer.caveat}</p>}
  </div>;
}

export function AssistantDrawer({ open, onOpen, onClose, page, project, run, navigate }: AssistantDrawerProps) {
  const runId = run?.detail.run_id ?? '';
  // Keep the drawer's data requests dormant until it is opened; the launch
  // button should not add a sampled-counter request to every page.
  const load = useSimLoad(open ? runId : '');
  const [selected, setSelected] = useChannelSelection(runId);
  const { picks, picking } = useAssistantContext();
  const [capKey, setCapKey] = useState(0);
  const capabilities = useGatewayDocument(
    open ? `assistant-capabilities:${capKey}` : 'assistant-capabilities-idle',
    () => open ? gateway.agentCapabilities() : Promise.resolve({}),
  );
  const [mode, setMode] = useState<'local' | 'model'>('local');
  const [messages, setMessages] = useState<Message[]>([]);
  const [contextOpen, setContextOpen] = useState(false);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [modelHelp, setModelHelp] = useState(false);
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:11434/v1');
  const [modelName, setModelName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const startupCommand = useMemo(() => {
    const env = `VERITX_AI_BASE_URL="${baseUrl.trim()}" VERITX_AI_MODEL="${modelName.trim()}"${apiKey.trim() ? ` VERITX_AI_API_KEY="${apiKey.trim()}"` : ''}`;
    return [
      '# Desktop app: set the environment before launch',
      `${env} srota-studio`,
      '',
      '# Dev gateway',
      `${env} ${GATEWAY_START}`,
    ].join('\n');
  }, [baseUrl, modelName, apiKey]);

  const context = useMemo(() => buildAssistantContext({
    page, project, run,
    channels: load.data?.channels ?? [],
    selected,
    measuredPhase: load.phase,
    measuredReason: load.reason,
  }), [page, project, run, load.data, load.phase, load.reason, selected]);
  const packet = useMemo(() => buildContextPacket({
    route: page?.id ?? '',
    page: page ? { title: page.title, group: page.group } : null,
    project,
    run,
    topology: run && project && run.detail.revision_id === project.detail.active_revision_id ? project.topology : null,
    load: load.data ?? null,
    picks,
  }), [page, project, run, load.data, picks]);
  const questions = useMemo(() => suggestedQuestions(context), [context]);
  const pickedQuestions = useMemo(() => picks.length ? pickedSuggestions(packet) : [], [picks.length, packet]);
  const welcome = useMemo(() => picks.length ? toAssistantAnswer(answerLocally('What context is attached?', packet)) : answerQuestion(context.measured ? 'overview' : 'page', context), [picks.length, packet, context]);
  const packetBytes = useMemo(() => contextPacketSize(packet), [packet]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if (typing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'i') {
        event.preventDefault();
        if (isPickingContext()) stopPicking(); else { onOpen(); startPicking(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, picking, onOpen, onClose]);
  const modelReady = !!capabilities.data?.configured;
  const modelReason = capabilities.error ?? capabilities.data?.reason ?? 'Model transport is not configured.';
  const runLabel = run?.detail.display_name ?? (context.run ? shortRun(context.run) : 'no run');
  const projectShort = context.project?.split(' · ')[0] ?? 'No project';
  const revisionShort = context.revision?.split('-').pop() ?? 'no revision';
  const runShort = runLabel.split(' · ').find(part => part !== revisionShort) ?? runLabel.split(' · ')[0];
  const pageShort = (page?.short ?? context.pageTitle).split(' & ')[0];

  const go = (action: AssistantAction) => {
    if (action.channel && runId) setSelected(action.channel);
    if (action.page) navigate(action.page as PageId);
    const settle = () => {
      if (action.channel) revealChannelDetail();
      if (action.scroll) document.getElementById(action.scroll)?.scrollIntoView({ block: 'start' });
    };
    if (action.page) window.setTimeout(settle, 120); else settle();
  };

  const append = (question: string, answer: AssistantAnswer, source: 'local' | 'model' = 'local') => {
    setMessages(rows => [...rows, { role: 'user', text: question }, { role: 'assistant', answer, source }]);
  };

  const ask = (question: AssistantQuestion | string, label: string) => {
    if (busy) return;
    setError('');
    if (picks.length) { append(label, toAssistantAnswer(answerLocally(label, packet))); return; }
    append(label, answerQuestion(question as AssistantQuestion, context));
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setError('');
    if (mode === 'local') {
      append(text, picks.length ? toAssistantAnswer(answerLocally(text, packet)) : answerFreeText(text, context));
      setInput('');
      return;
    }
    if (!modelReady || !project) {
      setError(modelReason);
      return;
    }
    setBusy(true);
    append(text, { paragraphs: ['Waiting for the configured model…'], evidence: [], actions: [] }, 'model');
    setInput('');
    try {
      const history = messages.slice(-10).map(row => ({
        role: row.role,
        content: row.role === 'user' ? row.text : row.answer.paragraphs.join(' '),
      }));
      const prompt = [
        'You are a read-only analysis guide for Srota Studio.',
        'Use only the JSON context below. Do not invent measurements, causes, hardware qualification, power, area, or paths.',
        'Cite the field values you rely on. If the answer is not in the context, say which value is missing.',
        'Keep the answer under 200 words.',
        '',
        'CONTEXT:',
        JSON.stringify(context),
        '',
        'SELECTED CONTEXT:',
        JSON.stringify(packet),
        '',
        'QUESTION:',
        text,
      ].join('\n');
      const response = await gateway.agentChat(project.detail.project.project_id, {
        message: prompt,
        history,
        allowModel: true,
        includeDraft: false,
        context: packet,
      });
      const body = typeof response.text === 'string' ? response.text.trim() : '';
      setMessages(rows => [...rows, { role: 'assistant', source: 'model', answer: {
        paragraphs: [body || 'The model returned no text.'],
        evidence: [],
        actions: [{ label: 'Open analysis summary', page: 'analysis/summary' }, { label: 'Inspect evidence', page: 'verify/evidence' }],
        caveat: 'Model phrasing is a suggestion, not evidence. The context pack remains the authority.',
      } }]);
    } catch (cause) {
      setError(gatewayReason(cause));
    } finally {
      setBusy(false);
    }
  };

  const copyStartup = async () => {
    try {
      await navigator.clipboard.writeText(startupCommand);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const openModelSettings = () => {
    setSaveError('');
    if (capabilities.data?.base_url) setBaseUrl(capabilities.data.base_url);
    if (capabilities.data?.model) setModelName(capabilities.data.model);
    setModelHelp(true);
  };

  const saveModel = async () => {
    if (saving || !baseUrl.trim() || !modelName.trim()) return;
    setSaveError('');
    setSaving(true);
    try {
      await gateway.setAgentConfig({ baseUrl: baseUrl.trim(), model: modelName.trim(), apiKey: apiKey.trim() || undefined });
      setModelHelp(false);
      setApiKey('');
      setCapKey(value => value + 1);
    } catch (cause) {
      const reason = gatewayReason(cause);
      setSaveError(reason.includes('(404)') ? 'This gateway build does not expose saved model settings yet. Use the startup command below, or restart the gateway from this build.' : reason);
    } finally {
      setSaving(false);
    }
  };

  if (picking) return <PickerLayer />;

  if (!open) return null;

  return <>
  <aside className="assistant-drawer" id="assistant-drawer" aria-label="Contextual assistant">
    <div className="assistant-head">
      <span className="assistant-mark"><Icon name="assistant" size={14} /></span>
      <h2>Contextual assistant</h2>
      <Badge>Read-only</Badge>
      <div className="segmented assistant-modes" role="group" aria-label="Assistant mode">
        <button type="button" className={mode === 'local' ? 'active' : ''} aria-pressed={mode === 'local'} onClick={() => setMode('local')}>Local</button>
        <button type="button" className={mode === 'model' ? 'active' : ''} aria-pressed={mode === 'model'} onClick={() => setMode('model')}>Model-assisted</button>
      </div>
      <button type="button" className="icon-button assistant-close" onClick={onClose} aria-label="Close assistant"><Icon name="close" size={14} /></button>
    </div>

    <div className="assistant-context">
      <div className="assistant-context-line" title={`${context.project ?? 'No project'} · ${context.revision ?? 'no revision'} · ${runLabel} · ${context.pageTitle}${context.selection ? ` · ${context.selection}` : ''}`}>
        <b>{projectShort}</b><span className="sep">·</span>
        <span>{revisionShort}</span><span className="sep">·</span>
        <span>{runShort}</span><span className="sep">·</span>
        <span>{pageShort}</span>
        {context.selection && <><span className="sep">·</span><span className="accent">{context.selection}</span></>}
      </div>
      <div className="assistant-context-actions">
        <button type="button" className="text-button" onClick={startPicking} title="Pick context; hold Shift while clicking to add more than one"><Icon name="target" size={11} /> Pick context</button>
        <button type="button" className="text-button" onClick={() => setContextOpen(value => !value)} aria-expanded={contextOpen} aria-controls="assistant-context-panel">{contextOpen ? 'Hide context' : 'Preview context'}</button>
        {picks.length > 0 && <button type="button" className="text-button" onClick={clearPicks}>Clear picks</button>}
        <span>Nothing is sent until you ask</span>
      </div>
      {picks.length > 0 && <div className="assistant-picks">
        {picks.map(pick => <span className="context-chip accent" key={`${pick.kind}:${pick.id}`} onMouseEnter={() => flashContextTarget(pick.kind, pick.id)}>
          <button type="button" className="chip-jump" title={`Show ${pick.label} on the page`} onClick={() => findContextTarget(pick.kind, pick.id)?.scrollIntoView({ block: 'center', behavior: 'smooth' })}><b>{pick.label}</b></button>
          <button type="button" className="chip-remove" aria-label={`Remove ${pick.label} from context`} onClick={() => removePick(pick.kind, pick.id)}><Icon name="close" size={9} /></button>
        </span>)}
      </div>}
    </div>

    <div className="assistant-body">
      {mode === 'model' && <Notice tone={modelReady ? 'blue' : 'amber'}>
        <span>{modelReady
          ? `Model-assisted is configured${capabilities.data?.model ? ` (${capabilities.data.model})` : ''}.`
          : `Model-assisted unavailable: ${modelReason} Local answers still work.`}</span>
        <div className="assistant-notice-actions">
          <button type="button" className="text-button" onClick={openModelSettings}>Model settings</button>
          <button type="button" className="text-button" onClick={() => setCapKey(value => value + 1)}>Check again</button>
        </div>
      </Notice>}

      {contextOpen && <div className="assistant-context-panel" id="assistant-context-panel">
        <div className="assistant-context-panel-head"><strong>Context pack</strong><span>what the assistant can see</span></div>
        <dl className="assistant-context-props">
          <div><dt>Project</dt><dd>{context.project ?? '—'}</dd></div>
          <div><dt>Revision</dt><dd className="mono">{context.revision ?? '—'}</dd></div>
          <div><dt>Run</dt><dd>{runLabel}</dd></div>
          <div><dt>Backend</dt><dd>{context.backend ?? '—'}</dd></div>
          <div><dt>Page</dt><dd>{context.pageTitle}</dd></div>
          <div><dt>Selection</dt><dd>{context.selection ?? '—'}</dd></div>
          <div><dt>Active channels</dt><dd>{context.measured ? `${context.measured.active} / ${context.measured.channels}` : 'not available'}</dd></div>
          <div><dt>Qualification</dt><dd>{context.qualification ?? 'not declared'}</dd></div>
        </dl>
        <pre className="assistant-context-json">{JSON.stringify(context, null, 2)}</pre>
        {picks.length > 0 && <div className="assistant-picked-pack">
          <div className="assistant-context-panel-head"><strong>Picked context</strong><span>{packetBytes.toLocaleString()} B · {picks.length} object{picks.length === 1 ? '' : 's'}</span></div>
          <pre className="assistant-context-json">{JSON.stringify(packet, null, 2)}</pre>
        </div>}
      </div>}

      <section className="assistant-suggested" aria-label="Suggested questions">
        <div className="assistant-section-head"><h3>Suggested for this {picks.length ? 'context' : 'view'}</h3><span>{picks.length ? 'from the picked objects' : 'generated from the current run'}</span></div>
        <div className="assistant-question-grid">
          {(picks.length ? pickedQuestions.map(label => ({ id: label, label })) : questions).map(question => <button key={question.id} type="button" onClick={() => ask(question.id, question.label)}>{question.label}</button>)}
        </div>
      </section>

      <div className="assistant-thread" aria-live="polite">
        {messages.length === 0 && <div className="assistant-message assistant">
          <span className="assistant-mark small"><Icon name="assistant" size={11} /></span>
          <AnswerView answer={welcome} source="local" onAction={go} />
        </div>}
        {messages.map((message, index) => message.role === 'user'
          ? <div key={index} className="assistant-user"><span>{message.text}</span></div>
          : <div key={index} className="assistant-message assistant"><span className="assistant-mark small"><Icon name="assistant" size={11} /></span><AnswerView answer={message.answer} source={message.source} onAction={go} /></div>)}
      </div>

      {error && <Notice tone="red">{error}</Notice>}

      <div className="assistant-related">
        <div className="assistant-section-head"><h3>Related views</h3></div>
        <div className="assistant-related-grid">
          <button type="button" onClick={() => go({ label: 'Open analysis summary', page: 'analysis/summary' })}>Analysis summary</button>
          <button type="button" onClick={() => go({ label: 'Open traffic matrix', page: 'analysis/matrix' })}>Traffic matrix</button>
          <button type="button" onClick={() => go({ label: 'Compare runs', page: 'analysis/comparison' })}>Compare runs</button>
          <button type="button" onClick={() => go({ label: 'Inspect evidence', page: 'verify/evidence' })}>Evidence detail</button>
        </div>
      </div>
    </div>

    <div className="assistant-composer">
      <div className="assistant-composer-box">
        <textarea aria-label="Ask the contextual assistant" rows={2} value={input} disabled={busy} placeholder={mode === 'model' ? 'Ask about this run (evidence-only prompt)…' : 'Ask about this run…'} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} />
        <div className="assistant-composer-row">
          <span className="assistant-attach">Run summary</span>
          <span className="assistant-attach">Selection</span>
          <span className="assistant-attach muted">Draft not attached</span>
          <button type="button" className="button primary" disabled={!input.trim() || busy || (mode === 'model' && !modelReady)} title={mode === 'model' && !modelReady ? modelReason : undefined} onClick={() => void send()}>{busy ? 'Waiting for model…' : mode === 'model' ? 'Send to model' : 'Explain locally'}</button>
        </div>
      </div>
    </div>
  </aside>

  {modelHelp && <Dialog title="Model assistance settings" onClose={() => setModelHelp(false)}>
    <Notice tone="blue">Save writes a private config file for this local gateway, so it applies without a restart. Environment variables still take precedence.</Notice>
    <form className="assistant-model-form" onSubmit={event => { event.preventDefault(); void saveModel(); }}>
      <Field label="Base URL" hint="OpenAI-compatible endpoint root, without /chat/completions.">
        <input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="http://127.0.0.1:11434/v1" spellCheck={false} />
      </Field>
      <Field label="Model" hint="The model name that endpoint expects.">
        <input value={modelName} onChange={event => setModelName(event.target.value)} placeholder="qwen3:32b" spellCheck={false} />
      </Field>
      <Field label="API key (optional)" hint="Leave blank to keep the saved key. Required for non-loopback endpoints; stored locally with restricted permissions where supported and never returned to this page.">
        <input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder="leave blank to keep saved key" autoComplete="off" />
      </Field>
    </form>
    {saveError && <Notice tone="red">{saveError}</Notice>}
    <details className="assistant-model-fallback">
      <summary>Use an environment variable instead</summary>
      <pre className="assistant-model-command">{startupCommand}</pre>
      <Button onClick={() => void copyStartup()}>{copied ? 'Copied' : 'Copy startup command'}</Button>
    </details>
    <div className="assistant-model-actions">
      <Button primary disabled={saving || !baseUrl.trim() || !modelName.trim()} onClick={() => void saveModel()}>{saving ? 'Saving…' : 'Save to gateway'}</Button>
    </div>
  </Dialog>}
  </>;
}
