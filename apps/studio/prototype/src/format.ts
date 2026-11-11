// One implementation of the small formatting helpers the live views were each redefining.
export const shortText = (value: string | null | undefined, keep = 20, fallback = '—') => value ? `${value.slice(0, keep)}…` : fallback;

export const num = (value: number | null | undefined, unit = '', digits = 3) => value === null || value === undefined ? '—' : `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${unit}`;

export const bytes = (value?: number | null) => value === null || value === undefined ? '—'
  : value >= 2 ** 30 ? `${(value / 2 ** 30).toFixed(3)} GiB`
  : value >= 2 ** 20 ? `${(value / 2 ** 20).toFixed(3)} MiB`
  : value >= 1024 ? `${(value / 1024).toFixed(2)} KiB`
  : `${value} B`;

// Long declared-data lists are bounded in place; every table uses the same threshold.
export const cappedClass = (count: number, limit = 12) => count > limit ? ' capped' : '';

export const stamp = (value?: string | null) => value ? value.replace('T', ' ').replace('+00:00', 'Z') : '—';

// Run evidence carries content identities for integrity checks. They are useful to the gateway,
// not to someone reading a document, so previews omit them while downloads keep the original.
const identityKey = /(sha256|sha-256|fingerprint|digest|(^|_)hash($|_))/i;
const identityValue = /^(sha256:)?[0-9a-f]{40,}$/i;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

export function withoutIdentity(value: unknown): unknown {
  if (typeof value === 'string') return identityValue.test(value) ? '[identity omitted]' : value;
  if (Array.isArray(value)) return value.map(withoutIdentity);
  if (!isRecord(value)) return value;
  return Object.fromEntries(Object.entries(value)
    .filter(([key, child]) => !identityKey.test(key) && !(typeof child === 'string' && identityValue.test(child)))
    .map(([key, child]) => [key, withoutIdentity(child)]));
}

export function redactIdentityText(text: string): string {
  return text
    .replace(/"([^"]*)"\s*:\s*(?:"(?:\\.|[^"\\])*"|null|true|false|-?\d+(?:\.\d+)?)\s*,?/g, (match, key: string) => identityKey.test(key) ? '' : match)
    .replace(/\b(?:sha256:)?[0-9a-f]{40,}\b/gi, '[identity omitted]');
}
