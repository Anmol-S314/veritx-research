import { useMemo, useState } from 'react';
import type { LoadedProject } from './project';
import { buildFabricAnalysis, type AnalysisCheck, type CheckStatus } from './fabricAnalysis';
import { Assumptions, Badge, Empty, Icon, Inspector, Notice, PageLink, Properties } from './ui';

const tone = (status: CheckStatus): 'green' | 'amber' | 'red' | 'neutral' =>
  status === 'PASS' ? 'green' : status === 'WARN' ? 'amber' : status === 'FAIL' ? 'red' : 'neutral';

const groupTitle: Record<AnalysisCheck['group'], string> = {
  address: 'Address map',
  agents: 'Agents & seats',
  routing: 'Routing & deadlock',
  topology: 'Topology',
  certificate: 'Compiler certificate',
  rtl: 'RTL reach',
};

function CheckList({ checks, onSelect, selected }: { checks: AnalysisCheck[]; onSelect: (id: string) => void; selected: string | null }) {
  return <div className="check-list" role="list">
    {checks.map(check => <button type="button" role="listitem" key={check.id} className={`check-row${selected === check.id ? ' selected' : ''}`} aria-pressed={selected === check.id} onClick={() => onSelect(check.id)}>
      <Badge tone={tone(check.status)}>{check.status}</Badge>
      <span className="check-copy"><strong>{check.title}</strong><small>{check.detail}</small></span>
      <Icon name="arrow" size={13} />
    </button>)}
  </div>;
}

export function FabricAnalysisView({ data }: { data: LoadedProject }) {
  const analysis = useMemo(() => buildFabricAnalysis(data.request, data.topology, data.compileResult), [data.request, data.topology, data.compileResult]);
  const [selected, setSelected] = useState<string | null>(analysis.checks[0]?.id ?? null);
  const [filter, setFilter] = useState<'all' | CheckStatus>('all');
  const selectedCheck = analysis.checks.find(check => check.id === selected) ?? null;
  const shown = filter === 'all' ? analysis.checks : analysis.checks.filter(check => check.status === filter);
  const draftDiffers = !!data.draftMeta?.dirty;
  const overall = draftDiffers ? 'WARN' : analysis.counts.FAIL ? 'FAIL' : analysis.counts.WARN ? 'WARN' : 'PASS';
  const previewReach = analysis.rtlRows.filter(row => row.status === 'reaches-preview').length;

  if (!data.request) return <div className="view-main"><Empty title="No draft request is available">
    The gateway did not return a draft for this project. Address, routing and RTL checks need the saved draft; the active revision's topology is not substituted for it.
  </Empty></div>;

  return <div className="view-layout"><div className="view-main">
    <div className="fabric-toolbar">
      <div className="fabric-toolbar-main">
        <Badge tone={tone(overall)}>Static verdict · {overall}</Badge>
        <span className="mono fabric-counts">{analysis.counts.PASS} pass · {analysis.counts.WARN} warn · {analysis.counts.FAIL} fail · {analysis.counts['N/A']} n/a · {analysis.checks.length} checks</span>
      </div>
      <div className="segmented" role="group" aria-label="Filter checks">
        {(['all', 'PASS', 'WARN', 'FAIL', 'N/A'] as const).map(value => <button key={value} type="button" className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : value}</button>)}
      </div>
    </div>

    {data.topologyError && <Notice tone="amber">Topology unavailable: {data.topologyError}</Notice>}
    {data.compileResultError && <Notice tone="amber">Compile result unavailable: {data.compileResultError}</Notice>}
    {draftDiffers && <Notice tone="amber"><strong>The saved draft differs from the active revision.</strong> Address checks describe the draft; certificate, deadlock and resolved decode describe {data.detail.active_revision_id ?? 'the active revision'}. Recompile before treating the verdict as one claim.</Notice>}

    <CheckList checks={shown} onSelect={setSelected} selected={selected} />

    <Assumptions rows={[
      ['Source', 'Saved draft for declared controls; active revision certificate for compiled claims.'],
      ['Authority', 'Static rule check over the saved draft; the compiler re-derives on compile.'],
      ['Limit', 'Not a simulation, implementation RTL or hardware qualification.'],
    ]} />
  </div>

  <Inspector title="Check detail">
    {selectedCheck ? <>
      <h3>{selectedCheck.title}</h3>
      <Badge tone={tone(selectedCheck.status)}>{selectedCheck.status}</Badge>
      <p>{selectedCheck.detail}</p>
      <Properties rows={[
        ['Group', groupTitle[selectedCheck.group]],
        ['Citation', selectedCheck.citation],
        ['Evidence', selectedCheck.evidence ?? '—'],
        ...(selectedCheck.group === 'rtl' ? [['Preview reach', `${previewReach} of ${analysis.rtlRows.length} controls reach the preview`] as [string, string]] : []),
      ]} />
    </> : <Empty title="Select a check">Choose a check to read its citation and evidence.</Empty>}
    <div className="inspector-links">
      <PageLink page="design/agent-map">Edit the agent address map</PageLink>
      <PageLink page="flow/optimize">Edit fabric controls</PageLink>
    </div>
  </Inspector>
  </div>;
}

export function FabricAnalysisEmpty() {
  return <Empty title="Load a gateway project to analyse its fabric">
    The analysis reads the project draft, the revision topology and the compiled certificate. It does not invent a fabric when none is loaded.
  </Empty>;
}

export const FABRIC_ANALYSIS_PURPOSE = 'Static, spec-grounded checks for agent addresses, routing shapes, port budget, island confinement and what actually reaches RTL.';
