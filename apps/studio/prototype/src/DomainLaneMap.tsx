const ROW_H = 120;
const TOP = 28;
const HEADER_X = 16;
const HEADER_W = 168;
const HEADER_H = 72;
const CHIP_X = 204;
const CHIP_W = 124;
const CHIP_H = 56;
const CHIP_GAP = 132;
const PALETTE = ['#317da7', '#3f8a61', '#b5893a', '#8a6d3b', '#6b7f8f'];

function domainClass(domain: string) {
  return `domain-${domain.replaceAll('_', '-')}`;
}

export type DomainLane = { id: string; mhz?: number; note?: string };
export type DomainChip = { id: string; title: string; meta: string; detail: string; domain: string };

/** Domains are drawn as declared assignment lanes, not a clock tree. A chip
 *  outside `crossingDomain` is dashed because the crossing is declared and the
 *  synchroniser/bridge is not. */
export function DomainLaneMap({ domains, chips, crossingDomain, selected, onSelect, figcaption }: {
  domains: DomainLane[];
  chips: DomainChip[];
  crossingDomain?: string;
  selected?: string | null;
  onSelect?: (id: string) => void;
  figcaption?: string;
}) {
  const maxChips = Math.max(1, ...domains.map(domain => chips.filter(chip => chip.domain === domain.id).length));
  const width = Math.max(900, CHIP_X + maxChips * CHIP_GAP + 16);
  const height = TOP + Math.max(1, domains.length) * ROW_H + 20;
  return <figure className="topology-figure domain-figure">
    <div className="domain-map-scroll">
      <svg className="domain-map" viewBox={`0 0 ${width} ${height}`} role="group" aria-label={crossingDomain ? `Declared endpoint clock-domain assignment. Dashed endpoints cross to ${crossingDomain} without an established bridge.` : 'Declared endpoint clock-domain assignment.'}>
        <text className="domain-axis-label" x={HEADER_X} y={16}>Declared domain</text>
        <text className="domain-axis-label" x={CHIP_X} y={16}>Assigned endpoints</text>
        {domains.map((domain, row) => {
          const y = TOP + row * ROW_H;
          const members = chips.filter(chip => chip.domain === domain.id);
          const crossing = !!crossingDomain && domain.id !== crossingDomain;
          const color = PALETTE[row % PALETTE.length];
          return <g key={domain.id} className={`domain-row ${domainClass(domain.id)}`}>
            <rect className="domain-lane" x={196} y={y + 4} width={width - 212} height={ROW_H - 24} rx={4} />
            <rect className="domain-header" x={HEADER_X} y={y + 8} width={HEADER_W} height={HEADER_H} rx={4} />
            <rect className="domain-header-bar" x={HEADER_X} y={y + 8} width={4} height={HEADER_H} rx={2} style={{ fill: color }} />
            <text className="domain-name" x={HEADER_X + 14} y={y + 30}>{domain.id}</text>
            <text className="domain-meta" x={HEADER_X + 14} y={y + 48}>{domain.mhz ? `${domain.mhz} MHz · ${(1000 / domain.mhz).toFixed(3)} ns` : 'Declared assignment'}</text>
            <text className="domain-meta" x={HEADER_X + 14} y={y + 66}>{members.length} · {domain.note ?? 'not evaluated'}</text>
            {members.length === 0 && <text className="domain-empty" x={CHIP_X} y={y + 50}>No endpoint declares this domain.</text>}
            {members.map((chip, index) => {
              const x = CHIP_X + index * CHIP_GAP;
              const isCrossing = crossing && chip.domain !== crossingDomain;
              return <g key={chip.id} className={`domain-chip${chip.id === selected ? ' selected' : ''}${isCrossing ? ' crossing' : ''}`}
                role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined}
                aria-label={onSelect ? `Endpoint ${chip.id}, ${chip.meta}, ${chip.domain}` : undefined}
                onClick={onSelect ? () => onSelect(chip.id) : undefined}
                onKeyDown={onSelect ? event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(chip.id); } } : undefined}>
                <rect x={x} y={y + 16} width={CHIP_W} height={CHIP_H} rx={4} />
                <text className="domain-chip-id" x={x + 10} y={y + 34}>{chip.title}</text>
                <text className="domain-chip-meta" x={x + 10} y={y + 49}>{chip.meta}</text>
                <text className="domain-chip-meta" x={x + 10} y={y + 63}>{chip.detail}</text>
              </g>;
            })}
          </g>;
        })}
      </svg>
    </div>
    <div className="legend">
      {domains.map((domain, index) => <span key={domain.id}><i className="legend-dot" style={{ background: PALETTE[index % PALETTE.length], borderColor: PALETTE[index % PALETTE.length] }} />{domain.id}</span>)}
      {crossingDomain && <span><i className="legend-dot dashed" />Crosses to {crossingDomain} · bridge not established</span>}
      <span>{figcaption ?? 'Assignment is declared intent; no CDC or reset-domain analysis is implied.'}</span>
    </div>
  </figure>;
}
