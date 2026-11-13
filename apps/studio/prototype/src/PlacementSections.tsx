import type { ReactNode } from 'react';
import type { FloorplanDerived, FloorplanView, Topology } from './gateway';
import { Badge, Properties, Section } from './ui';
import { FloorplanMap, type FloorplanAnnotation } from './FloorplanMap';
import { LogicalRouterMap } from './LogicalRouterMap';

const mm2 = (um2: number) => `${(um2 / 1e6).toFixed(3)} mm²`;
const span = (value: { min: number | null; mean: number | null; max: number | null }, unit: string) =>
  value.min === null ? '—'
    : value.min === value.max ? `${value.min.toFixed(2)} ${unit}`
    : `${value.min.toFixed(2)}–${value.max?.toFixed(2)} ${unit} (mean ${value.mean?.toFixed(2)})`;

function planRows(plan: NonNullable<FloorplanView['floorplan']>, estimate: FloorplanDerived | null, hash: string | null): [string, ReactNode][] {
  const rows: [string, ReactNode][] = [
    ['Die', `${plan.die_width_um} × ${plan.die_height_um} µm · ${mm2(plan.die_width_um * plan.die_height_um)}`],
    ['Router rectangles', `${plan.routers.length} declared`],
  ];
  if (estimate) {
    rows.push(['Router area', `${mm2(estimate.routers.area_um2)} · ${(estimate.routers.utilization * 100).toFixed(1)}% of die`]);
    rows.push(['Links', `${estimate.links.channels} channels · ${span(estimate.links.length_um, 'µm')}`]);
  }
  rows.push(['Declared wire rule', `${plan.wire.ps_per_mm} ps/mm + ${plan.wire.fixed_ps} ps${estimate ? ` · ${span(estimate.links.delay_ps, 'ps')}` : ''}`]);
  rows.push(['Keepouts', plan.keepouts.length ? `${plan.keepouts.length} declared` : 'None declared']);
  rows.push(['Binding', hash ?? 'No topology hash bound to this geometry']);
  return rows;
}

/** Declared floorplan geometry and its declared wire rule, never a placer
 *  result. Coordinates are the topology's logical coordinates. */
export function PlacementSections({ view, derived, actions, banner, annotations = [], topology = null }: {
  view: FloorplanView | null;
  derived?: FloorplanDerived | null;
  actions?: ReactNode;
  banner?: ReactNode;
  annotations?: FloorplanAnnotation[];
  topology?: Topology | null;
}) {
  const plan = view?.floorplan ?? null;
  const estimate = derived ?? view?.derived ?? null;
  if (!plan) return <>{banner}{topology && <Section title="Logical router-coordinate map" actions={<Badge>{topology.routers.length} routers</Badge>}>
    <LogicalRouterMap topology={topology} />
  </Section>}<div className="toolbar toolbar-start">{actions}</div></>;
  return <>
    {banner}
    <Section title="Declared floorplan map" actions={<Badge>{plan.routers.length} routers</Badge>}>
      <FloorplanMap view={{ ...(view as FloorplanView), floorplan: plan }} annotations={annotations} />
    </Section>
    <Section title="Floorplan" actions={<>
      <Badge tone={estimate ? 'blue' : 'amber'}>{estimate ? 'declared and derived' : 'declared geometry'}</Badge>
      {actions}
    </>}>
      <Properties rows={planRows(plan, estimate, view?.topology_hash ?? null)} />
    </Section>
  </>;
}
