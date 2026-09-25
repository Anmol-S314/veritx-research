import type { ReactElement, ReactNode } from 'react';
import type { TopologyEndpoint, TopologyView } from '../types';
import { Hash } from './badges';

/**
 * Router / channel / endpoint inspection from the certified TopologyView.
 * Every field rendered is a real artifact field — router id/coordinates/
 * seat capacity, channel src/dst/ports/width/latency, endpoint kind/
 * group/instance/router/port — plus the channel-level route weight the
 * artifact carries when present. Nothing is derived from intent.
 */

export interface FabricSelection {
  kind: 'router' | 'channel' | 'endpoint';
  routerId?: number;
  channelId?: number;
  endpointId?: number;
}

function Row({ label, value }: { label: string; value: ReactNode }): ReactElement {
  return (
    <div className="kv">
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}

function RouterInspector({ topology, routerId, endpoints, channels }: {
  topology: TopologyView;
  routerId: number;
  endpoints: TopologyEndpoint[];
  channels: { channelId: number; src: number; dst: number; width: number }[];
}): ReactElement {
  const router = topology.routers.find((r) => r.router_id === routerId);
  if (!router) {
    return <p className="muted">Router {routerId} is not in the certified topology.</p>;
  }
  const attached = endpoints.filter((e) => e.router_id === routerId);
  const out = channels.filter((c) => c.src === routerId);
  const inc = channels.filter((c) => c.dst === routerId);
  return (
    <>
      <Row label="router" value={<code>R{routerId}</code>} />
      <Row label="coordinates" value={<code>[{router.coordinates.join(', ')}]</code>} />
      <Row label="seat capacity" value={String(router.seat_capacity)} />
      <Row label="attached endpoints" value={
        attached.length === 0
          ? <span className="muted">none</span>
          : <span>{attached.length} of {router.seat_capacity} seats</span>
      } />
      <Row label="channels" value={<span>{out.length} out · {inc.length} in</span>} />
      {attached.length > 0 && (
        <>
          <h4>Attached agents</h4>
          <table className="tbl">
            <thead>
              <tr><th>endpoint</th><th>kind</th><th>group</th><th>instance</th><th>port</th></tr>
            </thead>
            <tbody>
              {attached.map((e) => (
                <tr key={e.endpoint_id}>
                  <td><code>{e.endpoint_id}</code></td>
                  <td>{e.kind}</td>
                  <td className="num">{e.group_index}</td>
                  <td className="num">{e.instance_index}</td>
                  <td className="num">{e.port_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

function ChannelInspector({ topology, channelId }: {
  topology: TopologyView;
  channelId: number;
}): ReactElement {
  const channel = topology.channels.find((c) => c.channel_id === channelId);
  if (!channel) {
    return <p className="muted">Channel {channelId} is not in the certified topology.</p>;
  }
  const link = topology.physical_links.find(
    (l) => l.physical_link_id === channel.physical_link_id,
  );
  return (
    <>
      <Row label="channel" value={<code>{channelId}</code>} />
      <Row label="direction" value={
        <span><code>R{channel.src_router}</code> → <code>R{channel.dst_router}</code></span>
      } />
      <Row label="ports" value={
        <span>src {channel.src_port} · dst {channel.dst_port}</span>
      } />
      <Row label="width" value={`${channel.width_bits} bits`} />
      <Row label="latency" value={`${channel.latency_cycles} cycles`} />
      {typeof channel.route_weight === 'number' && (
        <Row label="route weight" value={String(channel.route_weight)} />
      )}
      {link && (
        <Row label="physical link" value={
          <span>
            <code>{link.physical_link_id}</code>
            {link.length_mm != null && ` · ${link.length_mm} mm`}
            {` · ${link.channel_ids.length} channels`}
          </span>
        } />
      )}
    </>
  );
}

function EndpointInspector({ topology, endpointId }: {
  topology: TopologyView;
  endpointId: number;
}): ReactElement {
  const endpoint = topology.endpoints.find((e) => e.endpoint_id === endpointId);
  if (!endpoint) {
    return <p className="muted">Endpoint {endpointId} is not in the certified topology.</p>;
  }
  return (
    <>
      <Row label="endpoint" value={<code>{endpointId}</code>} />
      <Row label="kind" value={endpoint.kind} />
      <Row label="group / instance" value={
        <span>{endpoint.group_index} / {endpoint.instance_index}</span>
      } />
      <Row label="attached at" value={
        <span>router <code>R{endpoint.router_id}</code>, port {endpoint.port_id}</span>
      } />
    </>
  );
}

/** The inspector panel. Renders nothing until the user selects something;
 * selection state is local to the canvas — inspection never mutates the
 * artifact data. */
export default function FabricInspector({ topology, selection, onClose }: {
  topology: TopologyView;
  selection: FabricSelection | null;
  onClose: () => void;
}): ReactElement | null {
  if (!selection) return null;

  const channels = topology.channels.map((c) => ({
    channelId: c.channel_id,
    src: c.src_router,
    dst: c.dst_router,
    width: c.width_bits,
  }));
  const routerId = selection.kind === 'router'
    ? selection.routerId
    : selection.kind === 'endpoint'
      ? topology.endpoints.find((e) => e.endpoint_id === selection.endpointId)
        ?.router_id
      : undefined;
  const routerEndpoints = topology.endpoints;
  const routerChannels = channels;

  let body: ReactElement | null = null;
  if (selection.kind === 'router' && routerId !== undefined) {
    body = (
      <RouterInspector
        topology={topology}
        routerId={routerId}
        endpoints={routerEndpoints}
        channels={routerChannels}
      />
    );
  } else if (selection.kind === 'channel' && selection.channelId !== undefined) {
    body = <ChannelInspector topology={topology} channelId={selection.channelId} />;
  } else if (selection.kind === 'endpoint' && selection.endpointId !== undefined) {
    body = <EndpointInspector topology={topology} endpointId={selection.endpointId} />;
  }
  if (!body) return null;

  return (
    <aside className="fabric-inspector" aria-label="Artifact inspector">
      <div className="head-actions">
        <h3>Inspect</h3>
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
      {body}
      <div className="kv">
        <span>topology identity</span>
        <Hash value={topology.topology_hash} />
      </div>
      <div className="kv">
        <span>attachment identity</span>
        <Hash value={topology.attachment_hash} />
      </div>
      <p className="muted">
        Fields above are read from the certified TopologyView the revision
        was verified against — nothing here comes from design intent.
      </p>
    </aside>
  );
}
