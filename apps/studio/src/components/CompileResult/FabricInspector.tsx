import type { ReactElement } from 'react';
import type {
  AddressDecodeGroup, CanonicalRoute, FabricGroup, MappingGroup,
  ResourcesGroup,
} from '../../api';
import { fmtNum, humanize } from '../badges';
import FabricInspector2D from '../FabricInspector2D';
import { EmptyState } from './EmptyState';
import { useSelection } from './selection';

export default function FabricInspector({ group, route, showRoute, mapping,
  resources, addressDecode, onJump }: {
  group: FabricGroup;
  route: CanonicalRoute | null;
  showRoute: boolean;
  mapping: MappingGroup;
  resources: ResourcesGroup;
  addressDecode: AddressDecodeGroup;
  onJump: (tab: string) => void;
}): ReactElement {
  const { selection, select } = useSelection();

  if (!group.available || !group.topology) {
    return (
      <section className="card">
        <h4>Fabric</h4>
        <EmptyState title="No materialized topology for this revision.">
          <p>Upstream derivation stopped before a topology existed, so there
          is no graph to inspect.</p>
        </EmptyState>
      </section>
    );
  }
  const topology = group.topology;
  const counts = group.counts;
  const aggregate = group.detail_level === 'AGGREGATE';

  const selRouter = selection.kind === 'router'
    ? topology.routers.find((r) => r.router_id === selection.id) ?? null
    : null;
  const selChannel = selection.kind === 'channel'
    ? topology.channels.find((c) => c.channel_id === selection.id) ?? null
    : null;
  const selEndpoint = selection.kind === 'endpoint'
    ? topology.endpoints.find((e) => e.endpoint_id === selection.id) ?? null
    : null;
  const routeUsesChannel = (id: number): boolean =>
    (route?.hops ?? []).some((h) => h.channel_id === id);
  const vcForClass = (cls: string): number[] => {
    const entry = (resources.traffic_class_to_vcs ?? [])
      .find(([c]) => c === cls);
    return entry?.[1] ?? [];
  };
  const rankForEndpoint = (endpointId: number): number | null =>
    mapping.rows.find((r) => r.endpoint_id === endpointId)?.rank ?? null;
  const rangeForEndpoint = (endpointId: number): string | null => {
    const row = addressDecode.rows.find(
      (r) => r.target_endpoint_id === endpointId);
    return row?.name ?? null;
  };

  return (
    <section className="card">
      <div className="inspector-head">
        <h4>Fabric</h4>
        <span className="muted">
          detail {group.detail_level}
          {group.detail_thresholds
            ? ` (full ≤ ${group.detail_thresholds.full_detail_max}, `
              + `routers ≤ ${group.detail_thresholds.router_detail_max})`
            : ''}
        </span>
      </div>
      {aggregate ? (
        <div className="fabric-aggregate">
          <p>
            <strong>{counts?.routers}</strong> routers ·{' '}
            <strong>{counts?.channels}</strong> channels ·{' '}
            <strong>{counts?.attached}</strong> attached ·{' '}
            <strong>{counts?.unused_seats}</strong> unused seats
          </p>
          <p className="muted">
            Above {group.detail_thresholds?.router_detail_max} routers the
            per-router graph is not drawn; the aggregate occupancy summary
            is. Nothing is hidden — the counts are the artifact's.
          </p>
        </div>
      ) : (
        <FabricInspector2D
          topology={topology}
          route={route}
          showRoute={showRoute}
          external={
            selection.kind === 'router' || selection.kind === 'channel'
            || selection.kind === 'endpoint'
              ? { kind: selection.kind,
                  id: typeof selection.id === 'number' ? selection.id : -1 }
              : { kind: null }
          }
          onSelectionChange={(s) => {
            if (s.kind === null || s.id == null) return;
            select({ kind: s.kind, id: s.id });
          }}
        />
      )}
      <p className="muted">
        routers {counts?.routers} · channels {counts?.channels} · seats{' '}
        {counts?.seats} · attached {counts?.attached} · unused{' '}
        {counts?.unused_seats} ·{' '}
        <code>{group.topology.topology_hash.slice(0, 18)}…</code>
      </p>

      {selRouter && (
        <div className="inspector-detail">
          <h5 className="inspector-label">
            Router {selRouter.router_id} — coordinates{' '}
            {(selRouter.coordinates ?? []).join(', ')}
          </h5>
          <div className="kv-grid">
            <div className="kv"><span>seat occupancy</span>
              <span className="num">
                {topology.endpoints.filter(
                  (e) => e.router_id === selRouter.router_id).length}
                /{selRouter.seat_capacity}
              </span></div>
            <div className="kv"><span>attached endpoints</span>
              <span className="num">
                {topology.endpoints.filter(
                  (e) => e.router_id === selRouter.router_id)
                  .map((e) => e.endpoint_id).join(', ') || '—'}
              </span></div>
            <div className="kv"><span>incident channels</span>
              <span className="num">
                {topology.channels.filter(
                  (c) => c.src_router === selRouter.router_id
                    || c.dst_router === selRouter.router_id).length}
              </span></div>
            <div className="kv"><span>routing/resource facts</span>
              <span className="muted">
                {fmtNum(resources.vc_count)} VCs ·{' '}
                {(resources.traffic_class_to_vcs ?? [])
                  .map(([c]) => c).join(', ') || 'no classes'}
              </span></div>
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => onJump('routing')}>→ Routing</button>
            <button className="btn btn-small"
                    onClick={() => onJump('resources')}>→ Resources</button>
            <button className="btn btn-small"
                    onClick={() => onJump('mapping')}>→ Mapping</button>
          </div>
        </div>
      )}

      {selChannel && (
        <div className="inspector-detail">
          <h5 className="inspector-label">
            Channel {selChannel.channel_id} — r{selChannel.src_router}.p
            {selChannel.src_port} → r{selChannel.dst_router}.p
            {selChannel.dst_port}
          </h5>
          <div className="kv-grid">
            <div className="kv"><span>width</span>
              <span className="num">{selChannel.width_bits} bits</span></div>
            <div className="kv"><span>latency</span>
              <span className="num">{selChannel.latency_cycles} cycles</span></div>
            <div className="kv"><span>route weight</span>
              <span className="num">{selChannel.route_weight ?? '—'}</span></div>
            <div className="kv"><span>on overlaid route</span>
              <span>{routeUsesChannel(selChannel.channel_id)
                ? 'yes — part of the canonical derived route'
                : 'no overlaid route uses this channel'}</span></div>
            <div className="kv"><span>VC participation</span>
              <span className="muted">
                {(resources.traffic_class_to_vcs ?? [])
                  .map(([c, vcs]) => `${c}: ${(vcs ?? []).join(',')}`)
                  .join(' · ') || '—'}
              </span></div>
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => {
                      select({ kind: 'routing_class',
                               id: resources.traffic_class_to_vcs?.[0]?.[0]
                                 ?? '' });
                      onJump('routing');
                    }}>→ Routing</button>
            <button className="btn btn-small"
                    onClick={() => onJump('resources')}>→ Resources</button>
          </div>
        </div>
      )}

      {selEndpoint && (
        <div className="inspector-detail">
          <h5 className="inspector-label">
            Endpoint {selEndpoint.endpoint_id} —{' '}
            {humanize(selEndpoint.kind)} #{selEndpoint.instance_index}
          </h5>
          <div className="kv-grid">
            <div className="kv"><span>router</span>
              <span className="num">{selEndpoint.router_id}</span></div>
            <div className="kv"><span>mapped rank</span>
              <span className="num">
                {rankForEndpoint(selEndpoint.endpoint_id) ?? 'idle — no rank'}
              </span></div>
            <div className="kv"><span>address range</span>
              <span>{rangeForEndpoint(selEndpoint.endpoint_id)
                ?? 'none declared'}</span></div>
            {route && vcForClass(route.routing_class).length > 0 && (
              <div className="kv"><span>route class VCs</span>
                <span className="num">
                  {vcForClass(route.routing_class).join(', ')}
                </span></div>
            )}
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => onJump('routing')}>→ Routing</button>
            <button className="btn btn-small"
                    onClick={() => onJump('resources')}>→ Resources</button>
            <button className="btn btn-small"
                    onClick={() => {
                      const rank = rankForEndpoint(selEndpoint.endpoint_id);
                      if (rank != null) {
                        select({ kind: 'rank', id: rank,
                                 secondary: selEndpoint.endpoint_id });
                      }
                      onJump('mapping');
                    }}>→ Mapping</button>
          </div>
        </div>
      )}
    </section>
  );
}
