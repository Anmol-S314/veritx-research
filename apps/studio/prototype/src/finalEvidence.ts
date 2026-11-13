import type { CatalogRtlSupport } from './gateway';

/** The final-implementation evidence is keyed by family name (`gec_hybrid`,
 *  `gec_mecs`), while the preview support reports the short topology kind
 *  (`gec`). Resolve the mode before looking up evidence, so a GEC project does
 *  not report “not exposed for gec” when its family is actually named. */
export function evidenceFamilyKey(
  support: CatalogRtlSupport | null | undefined,
  request: Record<string, unknown> | null | undefined,
): string | null {
  const raw = support?.topology_kind ?? support?.topology_family ?? null;
  const topology = request?.topology as { kind?: string; mode?: string } | undefined;
  const kind = String(topology?.kind ?? raw ?? '').toLowerCase();
  const mode = String(topology?.mode ?? '').toLowerCase();
  if (raw === 'gec' || kind === 'gec' || kind === 'gec_hybrid' || kind === 'gec_mecs') {
    if (mode.includes('hybrid') || kind.includes('hybrid')) return 'gec_hybrid';
    if (mode.includes('me') || mode.includes('multidrop') || kind.includes('mecs')) return 'gec_mecs';
  }
  return raw;
}
