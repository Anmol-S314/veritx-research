import { expect, test } from '@playwright/test';
import { STORAGE_KEY } from '../src/model';

test('agent configuration stays local, validates context policy, and does not grant runtime authority', async ({ page }) => {
  const remote: string[] = [];
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { remote.push(url.href); await route.abort(); } else await route.continue();
  });
  await page.goto('/#/agents/runtime');
  await page.getByLabel('Runtime endpoint URL').fill('https://example.com');
  await expect(page.getByRole('button', { name: 'Save connection intent locally' })).toBeDisabled();
  await page.getByLabel('Runtime endpoint URL').fill('http://127.0.0.1:3000');
  await page.getByLabel('Credential environment-reference name').fill('AGENT_TOKEN_REF');
  await page.getByRole('button', { name: 'Save connection intent locally' }).click();
  await expect(page.getByRole('button', { name: 'Test handshake unavailable' })).toBeDisabled();
  const config = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).agentIntent, STORAGE_KEY);
  expect(config.tokenReference).toBe('AGENT_TOKEN_REF');
  expect(config.endpoint).toBe('http://127.0.0.1:3000');
  await page.goto('/#/agents/assistant');
  await page.getByRole('button', { name: 'Inspect local context' }).click();
  await expect(page.locator('pre')).toContainText('not sent to any provider');
  await expect(page.getByRole('button', { name: 'Send to agent unavailable' })).toBeDisabled();
  await page.goto('/#/explore/brief');
  await page.getByRole('button', { name: 'Approve local scope preview' }).click();
  await page.goto('/#/agents/approvals');
  await page.getByRole('button', { name: 'Review local approval revocation' }).click();
  await page.getByRole('button', { name: 'Revoke local approval preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No approved local scope preview' })).toBeVisible();
  const state = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(state.approvedBrief).toBeNull();
  expect(state.draft.id).toBe('local-draft');
  expect(remote).toEqual([]);
});
