/** Canonical interface direction vocabulary (tracker M1-28).
 *
 *  Mirrors `veritx_dse/model/agent_interface.py` — the DECLARED role of an
 *  interface, never inferred from the node's `role`/AgentKind. An unset role is
 *  unconstrained: the node opts out of direction pairing until it is declared.
 */
export const INTERFACE_ROLES = [
  'INITIATOR',
  'TARGET',
  'BIDIRECTIONAL',
  'STREAM_SOURCE',
  'STREAM_SINK',
] as const;

export type InterfaceRole = (typeof INTERFACE_ROLES)[number];

export const isInterfaceRole = (value: unknown): value is InterfaceRole =>
  typeof value === 'string' && (INTERFACE_ROLES as readonly string[]).includes(value);

interface Capability { issue: boolean; receive: boolean }

const CAPABILITY: Record<InterfaceRole, Capability> = {
  INITIATOR: { issue: true, receive: false },
  TARGET: { issue: false, receive: true },
  BIDIRECTIONAL: { issue: true, receive: true },
  STREAM_SOURCE: { issue: true, receive: false },
  STREAM_SINK: { issue: false, receive: true },
};

/** A pairing is legal iff a request can flow at least one way: one endpoint
 *  issues while the other receives. `undefined` on either side is unconstrained
 *  and always legal. Returns a precise message, or null when compatible. */
export function directionPairProblem(
  a: InterfaceRole | undefined | null,
  b: InterfaceRole | undefined | null,
): string | null {
  if (a == null || b == null) return null;
  const ca = CAPABILITY[a];
  const cb = CAPABILITY[b];
  if ((ca.issue && cb.receive) || (ca.receive && cb.issue)) return null;
  return `${a} cannot pair with ${b}: neither endpoint can receive the other's requests`;
}
