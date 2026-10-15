/** Virtual-channel and QoS authoring operations (tracker M3-06/M3-07/M3-09).
 *
 *  Pure edits over the typed `vcConfig` contract: the virtual channels, the
 *  traffic-class → VC map, and the arbitration policy. `validateProject` owns
 *  the rules (unique ids, positive depth, known VC/class references); these
 *  functions only keep the config internally consistent — removing a VC drops
 *  the class rows that named it, and dropping a class prunes the arbitration
 *  maps so no dangling reference is left for the validator to trip over.
 */
import type { TrafficClassMappingV1, VcArbitrationV1, VcConfigV1, VirtualChannelV1 } from './project';

export const ARBITRATION_POLICIES: VcArbitrationV1['policy'][] = [
  'round_robin', 'fixed_priority', 'weighted_round_robin',
];

const prune = <T extends object>(value: T): T => {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) if (item !== undefined) out[key] = item;
  return out as T;
};

export const emptyVcConfig = (): VcConfigV1 => ({
  virtualChannels: [], trafficClassMap: [], arbitration: { policy: 'round_robin' },
});

/** The next `vc<n>` id no channel already carries. */
export function nextVcId(config: VcConfigV1): string {
  const used = new Set(config.virtualChannels.map((vc) => vc.id));
  let n = 0;
  while (used.has(`vc${n}`)) n += 1;
  return `vc${n}`;
}

/** Keep only the arbitration map entries whose class is still declared, and
 *  drop an empty map entirely (an empty map is a JSON object but the validator
 *  would still accept it — omitting it is the honest "nothing set"). */
function pruneArbitration(arbitration: VcArbitrationV1, declared: Set<string>): VcArbitrationV1 {
  const keep = (map?: Record<string, number>): Record<string, number> | undefined => {
    if (!map) return undefined;
    const kept = Object.fromEntries(Object.entries(map).filter(([key]) => declared.has(key)));
    return Object.keys(kept).length > 0 ? kept : undefined;
  };
  const next: VcArbitrationV1 = { policy: arbitration.policy };
  const priority = keep(arbitration.priorityByTrafficClass);
  const weight = keep(arbitration.weightByTrafficClass);
  if (priority) next.priorityByTrafficClass = priority;
  if (weight) next.weightByTrafficClass = weight;
  return next;
}

/** Add a virtual channel, or replace the one with the same id. */
export function upsertVc(config: VcConfigV1, vc: VirtualChannelV1): VcConfigV1 {
  const clean = prune(vc);
  const index = config.virtualChannels.findIndex((existing) => existing.id === clean.id);
  const virtualChannels = index >= 0
    ? config.virtualChannels.map((existing, i) => (i === index ? clean : existing))
    : [...config.virtualChannels, clean];
  return { ...config, virtualChannels };
}

/** Remove a virtual channel and any traffic-class row that named it. */
export function removeVc(config: VcConfigV1, id: string): VcConfigV1 {
  const trafficClassMap = config.trafficClassMap.filter((row) => row.vcId !== id);
  return {
    ...config,
    virtualChannels: config.virtualChannels.filter((vc) => vc.id !== id),
    trafficClassMap,
    arbitration: pruneArbitration(config.arbitration, new Set(trafficClassMap.map((row) => row.trafficClass))),
  };
}

/** Rename a traffic class, carrying its VC row and arbitration entries. */
export function renameTrafficClass(config: VcConfigV1, from: string, to: string): VcConfigV1 {
  if (!to || from === to) return config;
  const trafficClassMap = config.trafficClassMap.map((row) => (
    row.trafficClass === from ? { ...row, trafficClass: to } : row));
  const remap = (map?: Record<string, number>): Record<string, number> | undefined => (map
    ? Object.fromEntries(Object.entries(map).map(([key, value]) => [key === from ? to : key, value]))
    : undefined);
  const arbitration: VcArbitrationV1 = { policy: config.arbitration.policy };
  const priority = remap(config.arbitration.priorityByTrafficClass);
  const weight = remap(config.arbitration.weightByTrafficClass);
  if (priority) arbitration.priorityByTrafficClass = priority;
  if (weight) arbitration.weightByTrafficClass = weight;
  return { ...config, trafficClassMap, arbitration };
}

/** Set (or clear, with an empty `vcId`) the VC a traffic class maps to. */
export function setTrafficClassRow(
  config: VcConfigV1, trafficClass: string, vcId: string, qos?: number | null,
): VcConfigV1 {
  const others = config.trafficClassMap.filter((row) => row.trafficClass !== trafficClass);
  const row: TrafficClassMappingV1 = { trafficClass, vcId };
  if (qos !== undefined && qos !== null) row.qos = qos;
  const trafficClassMap = vcId ? [...others, row] : others;
  return {
    ...config,
    trafficClassMap,
    arbitration: pruneArbitration(config.arbitration, new Set(trafficClassMap.map((r) => r.trafficClass))),
  };
}

/** Change the arbitration policy, keeping only the map the new policy uses. */
export function setArbitrationPolicy(config: VcConfigV1, policy: VcArbitrationV1['policy']): VcConfigV1 {
  const arbitration: VcArbitrationV1 = { policy };
  if (policy === 'fixed_priority' && config.arbitration.priorityByTrafficClass) {
    arbitration.priorityByTrafficClass = config.arbitration.priorityByTrafficClass;
  }
  if (policy === 'weighted_round_robin' && config.arbitration.weightByTrafficClass) {
    arbitration.weightByTrafficClass = config.arbitration.weightByTrafficClass;
  }
  return { ...config, arbitration };
}

/** Set or clear one priority/weight value; a cleared map is omitted. */
export function setArbitrationValue(
  config: VcConfigV1,
  field: 'priorityByTrafficClass' | 'weightByTrafficClass',
  trafficClass: string,
  value: number | null,
): VcConfigV1 {
  const edited = { ...(config.arbitration[field] ?? {}) };
  if (value === null) delete edited[trafficClass];
  else edited[trafficClass] = value;
  const arbitration: VcArbitrationV1 = { policy: config.arbitration.policy };
  if (field !== 'priorityByTrafficClass' && config.arbitration.priorityByTrafficClass) {
    arbitration.priorityByTrafficClass = config.arbitration.priorityByTrafficClass;
  }
  if (field !== 'weightByTrafficClass' && config.arbitration.weightByTrafficClass) {
    arbitration.weightByTrafficClass = config.arbitration.weightByTrafficClass;
  }
  if (Object.keys(edited).length > 0) arbitration[field] = edited;
  return { ...config, arbitration };
}
