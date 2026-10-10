/** V5 authoring lens. The root is never flattened or replaced by its base. */
export function baseDocument(doc: Record<string, unknown>): Record<string, unknown> {
  if (doc.schema_version !== 5) return doc;
  const base = doc.base_v4;
  if (!base || typeof base !== 'object' || Array.isArray(base)) throw new Error('V5 base_v4 must be a record');
  return base as Record<string, unknown>;
}

export function withBaseDocument(root: Record<string, unknown>, base: Record<string, unknown>): Record<string, unknown> {
  if (root.schema_version !== 5) return base;
  const previous = baseDocument(root);
  if (!Array.isArray(base.agents) || !Array.isArray(previous.agents) || base.agents.length !== previous.agents.length)
    throw new Error('V5 agent groups cannot be added, removed or remapped by base controls');
  return { ...root, base_v4: base };
}

/** Only an explicit edit/save drops computed identities; imports remain strict. */
export function editableDocument(doc: Record<string, unknown>): Record<string, unknown> {
  if (doc.schema_version === 5) assertExactJsonNumbers(doc);
  const base = doc.schema_version === 5 ? baseDocument(doc) : null;
  const editableBase = base ? editableDocument(base) : null;
  if (!Object.prototype.hasOwnProperty.call(doc, 'design_hash')
      && !Object.prototype.hasOwnProperty.call(doc, 'guardrail_hash')
      && editableBase === base) return doc;
  const next = { ...doc };
  delete next.design_hash;
  delete next.guardrail_hash;
  if (editableBase) next.base_v4 = editableBase;
  return next;
}

/** JSON number precision is bounded by JavaScript, never silently rounded intent. */
export function assertExactJsonNumbers(value: unknown): void {
  if (typeof value === 'number' && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))))
    throw new Error('Studio cannot safely author integers outside the exact JavaScript range; use the strict canonical JSON API');
  if (Array.isArray(value)) value.forEach(assertExactJsonNumbers);
  else if (value && typeof value === 'object') Object.values(value).forEach(assertExactJsonNumbers);
}
