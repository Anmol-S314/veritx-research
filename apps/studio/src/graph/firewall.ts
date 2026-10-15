export interface FirewallRule {
  src: string;
  dst: string;
  perm: 'RO' | 'RW';
}

export interface FirewallBlock {
  default: 'deny';
  rules: FirewallRule[];
}

export interface FirewallRuleIssue {
  index: number;
  previousIndex: number | null;
  kind: 'duplicate' | 'conflict' | 'invalid';
  message: string;
}

/** Diagnose exact duplicate/conflicting cells and impossible graph references.
 * The current contract has no rule precedence, so no priority hierarchy is inferred. */
export function inspectFirewallRules(rules: readonly unknown[], nodeIds?: readonly string[]): FirewallRuleIssue[] {
  const first = new Map<string, { index: number; perm: FirewallRule['perm'] }>();
  const issues: FirewallRuleIssue[] = [];
  const available = nodeIds ? new Set(nodeIds) : null;
  rules.forEach((value, index) => {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      issues.push({ index, previousIndex: null, kind: 'invalid', message: 'rule must be an object with src, dst, and RO/RW perm' });
      return;
    }
    const rule = value as Record<string, unknown>;
    if (typeof rule.src !== 'string' || !rule.src || typeof rule.dst !== 'string' || !rule.dst
      || (rule.perm !== 'RO' && rule.perm !== 'RW')) {
      issues.push({ index, previousIndex: null, kind: 'invalid', message: 'rule must have non-empty src/dst and RO/RW perm' });
      return;
    }
    if (available) {
      if (!available.has(rule.src)) issues.push({ index, previousIndex: null, kind: 'invalid', message: `source ${rule.src} is not a graph node; rule cannot match` });
      if (!available.has(rule.dst)) issues.push({ index, previousIndex: null, kind: 'invalid', message: `target ${rule.dst} is not a graph node; rule cannot match` });
      if (rule.src === rule.dst) issues.push({ index, previousIndex: null, kind: 'invalid', message: `self-pair ${rule.src} → ${rule.dst} is not represented by the firewall matrix; rule cannot match` });
    }
    const key = JSON.stringify([rule.src, rule.dst]);
    const prior = first.get(key);
    if (prior) issues.push({
      index, previousIndex: prior.index,
      kind: prior.perm === rule.perm ? 'duplicate' : 'conflict',
      message: prior.perm === rule.perm
        ? `duplicate rule for ${rule.src} → ${rule.dst}`
        : `conflicting ${prior.perm}/${rule.perm} rules for ${rule.src} → ${rule.dst}`,
    });
    else first.set(key, { index, perm: rule.perm });
  });
  return issues;
}

const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

/** Return stable, explicit-deny firewall authoring data with no view state. */
export function setFirewallRow(
  current: readonly FirewallRule[], nodeIds: readonly string[], src: string, perm: FirewallRule['perm'] | 'none',
): FirewallRule[] {
  const rules = current.filter((rule) => rule.src !== src);
  if (perm !== 'none') for (const dst of nodeIds) if (src !== dst) rules.push({ src, dst, perm });
  return canonicalFirewall(rules).rules;
}

export function setFirewallColumn(
  current: readonly FirewallRule[], nodeIds: readonly string[], dst: string, perm: FirewallRule['perm'] | 'none',
): FirewallRule[] {
  const rules = current.filter((rule) => rule.dst !== dst);
  if (perm !== 'none') for (const src of nodeIds) if (src !== dst) rules.push({ src, dst, perm });
  return canonicalFirewall(rules).rules;
}

export function allowAllFirewallRules(nodeIds: readonly string[]): FirewallRule[] {
  const rules: FirewallRule[] = [];
  for (const src of nodeIds) for (const dst of nodeIds) {
    if (src !== dst) rules.push({ src, dst, perm: 'RW' });
  }
  return canonicalFirewall(rules).rules;
}

export function canonicalFirewall(rules: readonly FirewallRule[]): FirewallBlock {
  const copy = rules.map(({ src, dst, perm }) => ({ src, dst, perm }));
  copy.sort((a, b) => compare(a.src, b.src) || compare(a.dst, b.dst));
  return { default: 'deny', rules: copy };
}
