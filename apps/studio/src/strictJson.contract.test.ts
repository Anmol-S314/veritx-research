import { expect, it } from 'vitest';
import { parseExactJson } from './strictJson';

it.each([
  '1000000000.00000001', '1.0000000000000001', '0.10000000000000001',
  '9007199254740993', '9007199254740992', '1e400', '1e-400', '-1e-400',
  '1.00000000000000001e9', '9007199254740991.1',
])('refuses lossy numeric token %s before parsing into authored intent', token => {
  expect(() => parseExactJson(`{"nested":[${token}]}`)).toThrow(/exact JavaScript range/);
});

it.each([
  '{"frequency_hz":1,"frequency_hz":2}',
  '{"nested":{"id":1,"\\u0069d":2}}',
  '[{"service_cycles":1,"service_cycles":2}]',
  '{"__proto__":1,"__proto__":2}',
])('refuses duplicate decoded keys %s', text => {
  expect(() => parseExactJson(text)).toThrow(/Duplicate JSON key/);
});

it.each([
  '1', '9007199254740991', '-9007199254740991', '1.0', '1e3', '1e+03',
  '0.1', '1e-7', '1.0000000000000001e9', '-0', '0.00e9999999999999999999',
  '{"same":1,"nested":{"same":2},"text":"1.0000000000000001"}',
  '[true,false,null,{"quoted\\\"key":"escaped\\\\text"}]',
  '{"__proto__":{"literal":true}}',
])('retains exact supported JSON %s', text => {
  expect(parseExactJson(text)).toEqual(JSON.parse(text));
});

it.each(['', '{', '[1,]', '{"x":1,}', '01', '+1', '1.', '1e', 'NaN', 'Infinity',
  'true false', '{"x":1 "y":2}', '"\\q"', '"unclosed', '[1\u00a02]'])
('refuses malformed JSON %s', text => {
  expect(() => parseExactJson(text)).toThrow();
});
