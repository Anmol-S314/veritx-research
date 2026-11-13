import type { Draft } from './model';
import type { EndpointSeatModel } from './EndpointSeats';
import { localAgentGroups, localTopology } from './localDesign';

/** Projects the local sample draft onto the same shape a loaded revision
 *  supplies, so the sample and a live project render one implementation.
 *  Coordinates are the sample's logical (column, row) placement, not a floorplan. */
export function localEndpointSeats(draft: Draft): EndpointSeatModel {
  const agents = localAgentGroups(draft);
  const topology = localTopology(draft);
  return {
    agents,
    endpoints: topology.endpoints,
    topology,
    labelById: new Map(draft.endpoints.map((endpoint, index) => [index, endpoint.id])),
    sourceById: new Map(draft.endpoints.map((endpoint, index) => [index, endpoint.source])),
    agentForEndpoint: endpoint => agents[endpoint.group_index ?? 0] ?? null,
  };
}
