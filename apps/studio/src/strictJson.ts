/** Refuse duplicate keys and numeric intent lost by JSON.parse/stringify.
 * Decimal tokens must equal the decimal value that JavaScript will send back.
 * This is conservative authoring admission, not arbitrary-precision arithmetic.
 */
export function parseExactJson(text: string): unknown {
  let offset = 0;
  const fail = (message: string): never => { throw new SyntaxError(`${message} at JSON offset ${offset}`); };
  const space = (): void => { while (/[\x20\t\r\n]/.test(text[offset] ?? '') && offset < text.length) offset++; };
  const take = (char: string): void => {
    space();
    if (text[offset] !== char) fail(`Expected ${char}`);
    offset++;
  };
  const string = (): string => {
    take('"');
    const start = offset - 1;
    while (offset < text.length) {
      const char = text[offset++];
      if (char === '"') return JSON.parse(text.slice(start, offset)) as string;
      if (char === '\\') offset++;
    }
    return fail('Unterminated string');
  };
  // Normalize without exponent expansion, so even extreme exponent tokens are bounded.
  const decimal = (token: string): string => {
    const [mantissa, exponent = '0'] = token.toLowerCase().split('e');
    const negative = mantissa.startsWith('-');
    const [whole, fraction = ''] = (negative ? mantissa.slice(1) : mantissa).split('.');
    let digits = (whole + fraction).replace(/^0+/, '');
    if (!digits) return '0';
    const trailing = digits.length - digits.replace(/0+$/, '').length;
    digits = digits.slice(0, digits.length - trailing);
    const scale = BigInt(exponent) - BigInt(fraction.length) + BigInt(trailing);
    return `${negative ? '-' : ''}${digits}e${scale}`;
  };
  const value = (): void => {
    space();
    const char = text[offset];
    if (char === '"') { string(); return; }
    if (char === '{') {
      take('{'); space();
      const keys = new Set<string>();
      if (text[offset] !== '}') {
        while (true) {
          const key = string();
          if (keys.has(key)) fail(`Duplicate JSON key ${JSON.stringify(key)}`);
          keys.add(key); take(':'); value(); space();
          if (text[offset] !== ',') break;
          take(',');
        }
      }
      take('}'); return;
    }
    if (char === '[') {
      take('['); space();
      if (text[offset] !== ']') {
        while (true) {
          value(); space();
          if (text[offset] !== ',') break;
          take(',');
        }
      }
      take(']'); return;
    }
    const literal = /^(?:true|false|null)/.exec(text.slice(offset));
    if (literal) { offset += literal[0].length; return; }
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(offset));
    if (!match) fail('Expected JSON value');
    const token = match![0];
    const number = Number(token);
    if (!Number.isFinite(number) || (Number.isInteger(number) && !Number.isSafeInteger(number))
        || decimal(token) !== decimal(String(number)))
      fail('Studio cannot safely author numeric tokens outside the exact JavaScript range; use the strict canonical JSON API');
    offset += token.length;
  };
  value(); space();
  if (offset !== text.length) fail('Unexpected trailing JSON');
  return JSON.parse(text) as unknown;
}
