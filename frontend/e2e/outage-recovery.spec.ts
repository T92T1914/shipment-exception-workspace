import { expect, test, type Page, type Route } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const password = process.env.WORKSPACE_DEMO_PASSWORD;
if (!password) throw new Error('WORKSPACE_DEMO_PASSWORD must be set for the synthetic seeded accounts.');

test.describe.configure({ mode: 'serial' });

function expireLoginAdmission() {
  const python = process.env.WORKSPACE_FIXTURE_PYTHON;
  if (!python || !process.env.WORKSPACE_LOGIN_FIXTURE_URL) {
    throw new Error('The scoped login-admission fixture environment must be set explicitly.');
  }
  const result = spawnSync(python, ['../tools/browser_login_fixture.py', 'expire'], {
    cwd: process.cwd(), env: process.env, encoding: 'utf8', windowsHide: true,
    timeout: 10_000, maxBuffer: 64 * 1024,
  });
  if (result.error || result.status !== 0) throw new Error('The scoped admission fixture failed.');
  let acknowledgement;
  try { acknowledgement = JSON.parse(result.stdout.trim()); }
  catch { throw new Error('The scoped admission fixture did not return an acknowledgement.'); }
  if (acknowledgement?.command !== 'expire' || acknowledgement?.ok !== true) {
    throw new Error('The scoped admission fixture did not confirm expiry.');
  }
}

function observe(page: Page) {
  const failures: string[] = [];
  const origin = new URL(process.env.WORKSPACE_BASE_URL ?? 'http://127.0.0.1:8765').origin;
  page.on('pageerror', error => failures.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) failures.push(message.text());
  });
  page.on('request', request => {
    const url = new URL(request.url());
    if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== origin) failures.push('Unexpected external request.');
  });
  page.on('response', response => {
    if (response.status() >= 400 && !(response.status() === 503 && response.headers()['x-outage-fixture'] === 'classified')) {
      failures.push(`Unexpected HTTP ${response.status()} from ${new URL(response.url()).pathname}`);
    }
  });
  page.on('requestfailed', request => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') failures.push(`Failed request: ${new URL(request.url()).pathname}`);
  });
  return () => expect(failures).toEqual([]);
}

async function unavailable(route: Route, mutation = false) {
  await route.fulfill({ status: 503, contentType: 'application/json', headers: {
    'Cache-Control': 'no-store', 'X-Outage-Fixture': 'classified',
  }, body: JSON.stringify({ error: {
    code: 'dependency_unavailable',
    message: mutation
      ? 'The workspace is temporarily unavailable. An earlier change may already be saved. Retry the original request only while your current access permits it.'
      : 'The workspace is temporarily unavailable. Check your session, then refresh the records.',
  } }) });
}

async function login(page: Page) {
  expireLoginAdmission();
  await page.goto('/');
  await page.getByLabel('Email address', { exact: true }).fill('alex@northline.example');
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
  await expect(page.locator('.identity .access-role')).toHaveText('Operator');
  await expect(page.locator('.exception-row').first()).toBeVisible();
}

async function createRecord(page: Page, suffix: string, eventCount = 1) {
  const sessionResponse = await page.request.get('/api/session');
  expect(sessionResponse.status()).toBe(200);
  const session = await sessionResponse.json();
  const headers = {
    Origin: new URL(page.url()).origin, 'X-CSRF-Token': session.csrf_token,
    'X-Workspace-Context': session.session_context,
  };
  const reference = `NL-OUTAGE-${suffix}`;
  const created = await page.request.post('/api/exceptions', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: { reference, summary: 'Synthetic outage recovery', details: 'A disposable browser recovery fixture.', priority: 'normal' },
  });
  expect(created.status()).toBe(201);
  const id = (await created.json()).exception.id as string;
  // Setup uses ordinary authorized API writes. It is separate from response fault injection.
  for (let version = 1; version < eventCount; version++) {
    const changed = await page.request.post(`/api/exceptions/${id}/assign`, {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: { expected_version: version, assignee_id: version % 2 ? '00000000-0000-0000-0000-00000000000c' : null },
    });
    expect(changed.status()).toBe(200);
  }
  await page.evaluate(value => { window.location.hash = `exception/${value}`; }, id);
  await expect(page.locator('.detail-heading .reference')).toHaveText(reference);
  return { id, reference, session };
}

async function frameBarrier(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function readable(page: Page, screenshotName: string) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth,
    content: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
  const directory = process.env.WORKSPACE_SCREENSHOTS;
  if (directory) {
    await mkdir(directory, { recursive: true });
    await page.screenshot({ path: join(directory, screenshotName), fullPage: true, animations: 'disabled' });
  }
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  test(`${viewport.name} classified read outages explain explicit queue and history recovery`, async ({ page }) => {
    test.info().annotations.push({ type: 'response-fixture', description: 'Classified 503 responses replace selected browser reads. The database stays running; this is separate from native PostgreSQL interruption acceptance.' });
    await page.setViewportSize(viewport);
    await page.emulateMedia({ colorScheme: 'dark' });
    const assertBrowser = observe(page);
    await login(page);
    const { id } = await createRecord(page, `${viewport.name}-reads`, 21);
    let businessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    });
    if (viewport.name === 'narrow') {
      // The narrow layout shows either the queue or the selected detail.
      await page.getByRole('button', { name: 'Back to exceptions', exact: true }).click();
      await expect(page.getByLabel('Search references and summaries', { exact: true })).toBeVisible();
    }
    await page.route('**/api/exceptions?*', route => unavailable(route), { times: 1 });
    await page.getByLabel('Search references and summaries', { exact: true }).fill('NL-OUTAGE');
    await page.getByRole('button', { name: 'Search queue', exact: true }).click();
    await expect(page.locator('.queue-error')).toContainText('temporarily unavailable');
    await expect(page.locator('.queue-error')).not.toContainText('Change the search');
    const refresh = page.getByRole('button', { name: 'Refresh workspace', exact: true });
    await refresh.focus();
    await expect(refresh).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('.queue-error')).toHaveCount(0);
    if (viewport.name === 'narrow') {
      await page.getByRole('button', { name: new RegExp(`NL-OUTAGE-${viewport.name}-reads`) }).click();
    }
    await expect(page.locator('.detail-heading .reference')).toHaveText(`NL-OUTAGE-${viewport.name}-reads`);
    await page.route(`**/api/exceptions/${id}/history?*`, route => unavailable(route), { times: 1 });
    await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    await expect(page.locator('.history-error')).toContainText('temporarily unavailable');
    await expect(page.locator('.history-error')).not.toContainText('change may already');
    if (viewport.name === 'narrow') {
      await page.evaluate(() => { document.documentElement.style.fontSize = '32px'; });
    }
    await readable(page, `${viewport.name}-outage-read.png`);
    const retryHistory = page.getByRole('button', { name: 'Retry history page', exact: true });
    await retryHistory.focus();
    await expect(retryHistory).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('.history-error')).toHaveCount(0);
    await expect(page.locator('.history-list li')).toHaveCount(1);
    await expect(page.locator('.history-boundary')).toContainText('through version 21.');
    expect(businessPosts).toBe(0);
    assertBrowser();
  });

  test(`${viewport.name} classified mutation outage retains one intent through a matching session check and explicit retry`, async ({ page }) => {
    test.info().annotations.push({ type: 'response-fixture', description: 'The assignment commits through the actual API; only its browser-facing acknowledgement is replaced with a classified 503. This is deliberate response withholding, not naturally observed packet loss.' });
    await page.setViewportSize(viewport);
    await page.emulateMedia({ colorScheme: 'dark' });
    const assertBrowser = observe(page);
    await login(page);
    const { id, session } = await createRecord(page, `${viewport.name}-retry`);
    const attempts: { key: string | undefined; body: string | null }[] = [];
    await page.route(`**/api/exceptions/${id}/assign`, async route => {
      attempts.push({ key: route.request().headers()['idempotency-key'], body: route.request().postData() });
      if (attempts.length === 1) {
        expect((await route.fetch()).status()).toBe(200);
        await unavailable(route, true);
      } else await route.continue();
    });
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await expect(page.locator('.workspace-messages')).toContainText('temporarily unavailable');
    await expect(page.locator('.workspace-messages')).toContainText('may already be saved');
    await expect(page.locator('.workspace-messages')).not.toContainText('response was interrupted');
    await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeDisabled();
    const saved = await (await page.request.get(`/api/exceptions/${id}`)).json();
    expect(saved.exception.version).toBe(2);
    const checked = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
    const check = page.getByRole('button', { name: 'Check current session', exact: true });
    await check.focus();
    await expect(check).toBeFocused();
    await page.keyboard.press('Enter');
    const current = await (await checked).json();
    expect(current.session_context).toBe(session.session_context);
    expect(current.user.role).toBe('operator');
    const retry = page.getByRole('button', { name: 'Retry same change', exact: true });
    await expect(retry).toBeEnabled();
    await frameBarrier(page);
    expect(attempts).toHaveLength(1);
    if (viewport.name === 'narrow') await page.evaluate(() => { document.documentElement.style.fontSize = '32px'; });
    await readable(page, `${viewport.name}-outage-pending.png`);
    const replay = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/exceptions/${id}/assign`);
    await retry.focus();
    await expect(retry).toBeFocused();
    await page.keyboard.press('Enter');
    const replayed = await replay;
    expect(replayed.status()).toBe(200);
    expect(replayed.headers()['idempotency-replayed']).toBe('true');
    await expect(page.getByText('Assignment saved.', { exact: true })).toBeVisible();
    expect(attempts).toHaveLength(2);
    expect(attempts[0].key).toBeTruthy();
    expect(attempts[1]).toEqual(attempts[0]);
    expect(await (await page.request.get(`/api/exceptions/${id}`)).json()).toEqual(saved);
    assertBrowser();
  });

  test(`${viewport.name} classified session outage retires an uncertain change and recovers without a business replay`, async ({ page }) => {
    test.info().annotations.push({ type: 'response-fixture', description: 'One actual committed assignment acknowledgement and one authoritative session read are replaced with classified 503 responses. Existing session/context retirement remains authoritative.' });
    await page.setViewportSize(viewport);
    await page.emulateMedia({ colorScheme: 'dark' });
    const assertBrowser = observe(page);
    await login(page);
    const { id, reference } = await createRecord(page, `${viewport.name}-retire`);
    let businessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    });
    await page.route(`**/api/exceptions/${id}/assign`, async route => {
      expect((await route.fetch()).status()).toBe(200);
      await unavailable(route, true);
    }, { times: 1 });
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeEnabled();
    const saved = await (await page.request.get(`/api/exceptions/${id}`)).json();
    await page.route('**/api/session', route => unavailable(route), { times: 1 });
    await page.getByRole('button', { name: 'Check current session', exact: true }).click();
    await expect(page.locator('.workspace')).toHaveCount(0);
    await expect(page.locator('.identity')).toHaveCount(0);
    await expect(page.locator('.session-message')).toContainText('temporarily unavailable');
    await expect(page.locator('.session-message')).toContainText('current session could not be confirmed');
    await expect(page.locator('.session-message')).toContainText('An earlier change may already be saved. Its local retry was retired.');
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
    const check = page.getByRole('button', { name: 'Check current session', exact: true });
    await expect(check).toBeEnabled();
    await frameBarrier(page);
    expect(businessPosts).toBe(1);
    await readable(page, `${viewport.name}-outage-retired.png`);
    await check.focus();
    await expect(check).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
    await expect(page.locator('.detail-heading')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
    await page.getByLabel('Search references and summaries', { exact: true }).fill(reference);
    await page.getByRole('button', { name: 'Search queue', exact: true }).click();
    await page.getByRole('button', { name: new RegExp(reference) }).click();
    await expect(page.locator('.detail-heading .reference')).toHaveText(reference);
    await expect(page.locator('.record-meta')).toContainText('Version 2');
    expect(await (await page.request.get(`/api/exceptions/${id}`)).json()).toEqual(saved);
    expect(businessPosts).toBe(1);
    assertBrowser();
  });
}
