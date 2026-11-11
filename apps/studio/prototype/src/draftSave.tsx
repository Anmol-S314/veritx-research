import { useState, type ReactNode } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Badge, Button, Notice, PageLink } from './ui';

export type Draft = Record<string, any>;

/**
 * A topology document that agrees with the compiled revision. It is only used
 * when a v3 draft has to be migrated before it can carry a compute block.
 */
export function topologyIntentFor(project: LoadedProject): Draft | null {
  const request = project.request as Draft | null;
  const noc = request?.noc_config as Draft | undefined;
  const topology = project.topology;
  const family = (noc?.topology_family as string | undefined) ?? topology?.family;
  if (!family || !['mesh', 'concentrated_mesh', 'torus'].includes(family)) return null;
  const concentration = noc?.concentration ?? (family === 'concentrated_mesh' ? 4 : 1);
  if (topology && topology.family === family) {
    const coordinates = topology.routers
      .map(router => router.coordinates ?? [])
      .filter(value => value.length >= 2);
    const side = coordinates.length
      ? Math.max(...coordinates.map(value => Math.max(value[0], value[1]))) + 1
      : Math.round(Math.sqrt(topology.routers.length));
    return { kind: family, side_length: side, concentration };
  }
  // A fresh v3 draft can carry no compiled revision yet. The frozen v3
  // auto-sizing law derives the same square grid the migration would.
  const endpoints = ((request?.agents ?? []) as Draft[]).reduce((sum, agent) => sum + (Number(agent.count) || 0), 0);
  const radix = Number(noc?.radix) || Math.max(1, Math.ceil(Math.sqrt(Math.ceil(endpoints / concentration))));
  return { kind: family, side_length: radix, concentration };
}

export function draftSchema(project: LoadedProject): number | null {
  const value = (project.request as Draft | null)?.schema_version;
  return typeof value === 'number' ? value : null;
}

export function DraftContext({ project }: { project: LoadedProject }) {
  const schema = draftSchema(project);
  const dirty = project.draftMeta?.dirty === true;
  return <div className="studio-context">
    <Badge tone={dirty ? 'amber' : 'blue'}>{dirty ? 'Draft edited' : 'Live draft'}</Badge>
    <strong>{project.detail.project.name}</strong>
    <code>{project.detail.active_revision_id ?? 'no revision'}</code>
    {schema !== null && <small>schema v{schema}</small>}
    <span className="studio-context-spacer" />
    <span className="muted">Changes stay in the draft until compiled.</span>
  </div>;
}

type SaveOptions = {
  /** Compute stages exist only in schema v4, so a v3 draft is validated and migrated first. */
  needsV4?: boolean;
};

type SaveState = {
  busy: boolean;
  error: string;
  saved: string;
  save: (mutate: (base: Draft) => Draft, message: string, options?: SaveOptions) => Promise<boolean>;
};

export function useDraftSave(project: LoadedProject, notify: (message: string) => void): SaveState {
  const { reload } = useProject();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');

  const save = async (mutate: (base: Draft) => Draft, message: string, options?: SaveOptions) => {
    const request = project.request as Draft | null;
    if (!request) {
      setError('This project has no readable draft to save.');
      return false;
    }
    const schema = draftSchema(project);
    if (schema !== null && schema >= 5) {
      setError('This draft uses schema v5 nested intent. Edit it in the Project workflow draft editor.');
      return false;
    }
    setBusy(true); setError(''); setSaved('');
    try {
      let base = request;
      if (options?.needsV4 && schema !== null && schema < 4) {
        const topology = topologyIntentFor(project);
        if (!topology) {
          throw new Error('This v3 draft has no fabric declaration that the gateway can validate. Open Project workflow, choose Edit draft, and validate the topology once; then return here.');
        }
        const preview = await gateway.topologyPreview(project.detail.project.project_id, base, topology);
        if (!preview.request) throw new Error('The gateway returned no canonical request for this draft.');
        base = preview.request;
      }
      const next = mutate(base);
      await gateway.putDraft(project.detail.project.project_id, next, project.draftMeta?.revisionToken);
      setSaved(message);
      notify(message);
      reload();
      return true;
    } catch (caught) {
      setError(gatewayReason(caught));
      return false;
    } finally {
      setBusy(false);
    }
  };

  return { busy, error, saved, save };
}

export function DraftSaveBar({ dirty, valid, state, onSave, note, label = 'Save to draft' }: {
  dirty: boolean;
  valid: boolean;
  state: SaveState;
  onSave: () => void;
  note: ReactNode;
  label?: string;
}) {
  const status = state.saved && !dirty
    ? <><strong>Saved to the draft.</strong> Compile in <PageLink page="workloads/workflow">Project workflow</PageLink> to publish a revision.</>
    : dirty
      ? <><strong>Unsaved draft changes.</strong> {note}</>
      : <><strong>No changes to save.</strong> {note}</>;
  return <div className="save-bar">
    <div className="save-copy">
      <span>{status}</span>
      {state.error && <Notice tone="red">{state.error}</Notice>}
    </div>
    <Button primary disabled={!dirty || !valid || state.busy} onClick={onSave}>
      {state.busy ? 'Saving…' : label}
    </Button>
  </div>;
}

export function IssueList({ issues }: { issues: string[] }) {
  if (!issues.length) return null;
  return <ul className="issue-list" aria-label="Draft problems">
    {issues.slice(0, 6).map(issue => <li key={issue}>{issue}</li>)}
    {issues.length > 6 && <li>{issues.length - 6} more problems not shown.</li>}
  </ul>;
}

function numberText(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function integerText(value: string, minimum = 0): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum ? parsed : null;
}

export function optionalNumber(value: string): number | null {
  return value.trim() === '' ? null : numberText(value);
}
