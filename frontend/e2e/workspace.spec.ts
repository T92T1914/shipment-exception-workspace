import { expect, test, type Page, type Response } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const demoPassword = process.env.WORKSPACE_DEMO_PASSWORD;
if (!demoPassword) throw new Error('WORKSPACE_DEMO_PASSWORD must be set for the synthetic seeded accounts.');

test.describe.configure({ mode: 'serial' });

function observeBrowser(page: Page, options: { expectedStatus?: number; expectedFailedRequest?: RegExp } = {}) {
  const failures: string[] = [];
  const baseOrigin = new URL(process.env.WORKSPACE_BASE_URL ?? 'http://127.0.0.1:8765').origin;
  page.on('pageerror', error => failures.push(`Uncaught browser error: ${error.message}`));
  page.on('console', message => {
    // Browser-generated HTTP diagnostics are checked with their exact status below.
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) {
      failures.push(`Browser console error: ${message.text()}`);
    }
  });
  page.on('request', request => {
    const url = new URL(request.url());
    if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== baseOrigin) {
      failures.push(`Unexpected external request to ${url.origin}`);
    }
  });
  page.on('response', response => {
    if (response.status() >= 400 && response.status() !== options.expectedStatus) {
      failures.push(`Unexpected HTTP ${response.status()} from ${new URL(response.url()).pathname}`);
    }
  });
  page.on('requestfailed', request => {
    if (options.expectedFailedRequest?.test(new URL(request.url()).pathname)) return;
    if (request.failure()?.errorText === 'net::ERR_ABORTED') return;
    failures.push(`Failed browser request: ${new URL(request.url()).pathname}`);
  });
  return () => expect(failures, 'No unexpected browser errors or external network calls').toEqual([]);
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    content: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  expect(dimensions.content, 'Content fits the viewport without horizontal scrolling').toBeLessThanOrEqual(dimensions.viewport);
}

async function login(page: Page, organization: 'northline' | 'harbor' = 'northline', role: 'operator' | 'reviewer' = 'operator') {
  await page.goto('/');
  const email = page.getByLabel('Email address');
  await expect(email).toBeVisible();
  await email.focus();
  await expect(email).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
  await email.fill(role === 'reviewer'
    ? organization === 'northline' ? 'casey@northline.example' : 'taylor@harbor.example'
    : organization === 'northline' ? 'alex@northline.example' : 'jules@harbor.example');
  await page.getByLabel('Password', { exact: true }).fill(demoPassword!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
  await expect(page.locator('.identity')).toContainText(organization === 'northline' ? 'Northline Logistics' : 'Harbor Supply');
  await expect(page.locator('.identity .access-role')).toHaveText(role === 'operator' ? 'Operator' : 'Read-only reviewer');
  const seededReferences = organization === 'northline' ? ['NL-1042', 'NL-1086', 'NL-1091'] : ['HS-2057', 'HS-2073'];
  for (const reference of seededReferences) {
    const row = page.getByRole('button', { name: new RegExp(reference) });
    await expect(row).toBeVisible();
    await expect(row.locator('.reference')).toHaveText(reference);
    await expect(row.locator('.reference')).toHaveJSProperty('translate', false);
    await expect(row.locator('strong')).toHaveJSProperty('translate', true);
  }
  const references = await page.locator('.exception-row .reference').allTextContents();
  expect(references.length).toBeGreaterThanOrEqual(seededReferences.length);
  expect(references.every(reference => reference.startsWith(organization === 'northline' ? 'NL-' : 'HS-'))).toBe(true);
  // These are native translation hints, not a translation provider quality check.
  for (const control of [
    page.getByLabel('Search references and summaries', { exact: true }),
    page.getByRole('button', { name: 'Search queue', exact: true }),
    page.getByRole('button', { name: 'Clear search', exact: true }),
    page.getByLabel('Show exceptions', { exact: true }),
    page.getByRole('button', { name: 'Previous page', exact: true }),
    page.getByRole('button', { name: 'Next page', exact: true }),
  ]) await expect(control).toHaveJSProperty('translate', true);
}

async function openRecord(page: Page, reference: string) {
  await page.getByRole('button', { name: new RegExp(reference) }).click();
  const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
  await expect(detail.locator('.detail-heading .reference')).toHaveJSProperty('translate', false);
  await expect(detail.locator('.detail-heading h2')).toHaveJSProperty('translate', true);
  await expect(detail.locator('.detail-description p')).toHaveJSProperty('translate', true);
  return detail;
}

async function screenshot(page: Page, name: string) {
  const directory = process.env.WORKSPACE_SCREENSHOTS;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: join(directory, name), fullPage: true, animations: 'disabled' });
}

test('desktop assignment, resolution, reload and organization switch use persisted records', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  await expect(page.getByText('Synthetic workspace', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: /HS-20/ })).toHaveCount(0);
  const detail = await openRecord(page, 'NL-1042');
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Assignment saved.');
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  await expect(detail.locator('.history-list')).toContainText('Alex Morgan assigned Sam Rivera');

  const note = 'Receiving team confirmed the next appointment. Carrier and consignee received the updated handoff.';
  await page.getByLabel('Resolution note', { exact: true }).fill(note);
  await page.getByRole('button', { name: 'Confirm resolution', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Exception resolved.');
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await expect(detail.locator('.history-list li')).toHaveCount(2);
  await expect(page.getByLabel('Assigned to', { exact: true })).toBeDisabled();
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'desktop-resolved.png');

  await page.reload();
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(2);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
  await login(page, 'harbor');
  await expect(page.getByRole('button', { name: /NL-10/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /HS-2057/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /HS-2073/ })).toBeVisible();
  assertBrowser();
});

test('narrow mobile workflow assigns and resolves with readable list and detail navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  await assertNoHorizontalOverflow(page);
  const detail = await openRecord(page, 'NL-1086');
  await expect(page.getByRole('heading', { name: 'Your organization', exact: true })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Back to exceptions', exact: true })).toBeVisible();
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  await assertNoHorizontalOverflow(page);
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  const note = 'The synthetic manifest was reconciled with receiving. All twelve pallets are accounted for.';
  const input = page.getByLabel('Resolution note', { exact: true });
  await input.focus();
  await expect(input).toBeFocused();
  await input.fill(note);
  await page.getByRole('button', { name: 'Confirm resolution', exact: true }).click();
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(2);
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'mobile-resolved.png');
  await page.getByRole('button', { name: 'Back to exceptions', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your organization', exact: true })).toBeVisible();
  await expect(detail).not.toBeVisible();
  await page.getByLabel('Show exceptions', { exact: true }).selectOption('resolved');
  await expect(page.getByRole('button', { name: /NL-1086/ })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await openRecord(page, 'NL-1086');
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  assertBrowser();
});

test('two tabs reject a stale assignment and refresh before a new change', async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertFirst = observeBrowser(page);
  await login(page);
  const firstDetail = await openRecord(page, 'NL-1091');
  const second = await context.newPage();
  const assertSecond = observeBrowser(second, { expectedStatus: 409 });
  await second.goto(page.url());
  const secondDetail = second.getByRole('region', { name: 'Exception detail', exact: true });
  await expect(firstDetail.locator('.record-meta')).toContainText('Version 1');
  await expect(secondDetail.locator('.record-meta')).toContainText('Version 1');
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(firstDetail.locator('.record-meta')).toContainText('Version 2');
  await second.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Alex Morgan' });
  await second.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(second.getByRole('alert')).toContainText('Someone changed this exception');
  await expect(second.getByRole('button', { name: 'Save assignment', exact: true })).toBeDisabled();
  const recordId = new URL(page.url()).hash.split('/')[1];
  const afterConflictResponse = await second.request.get(`/api/exceptions/${recordId}`);
  expect(afterConflictResponse.status()).toBe(200);
  const afterConflict = await afterConflictResponse.json();
  expect(afterConflict.exception.version).toBe(2);
  expect(afterConflict.events).toHaveLength(1);
  await second.getByRole('button', { name: 'Refresh record', exact: true }).click();
  await expect(secondDetail.locator('.record-meta')).toContainText('Version 2');
  await expect(second.getByLabel('Assigned to', { exact: true })).toHaveValue(afterConflict.exception.assignee_id);
  await second.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Alex Morgan' });
  await second.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(secondDetail.locator('.record-meta')).toContainText('Version 3');
  await expect(secondDetail.locator('.history-list li')).toHaveCount(2);
  assertFirst(); assertSecond();
  await second.close();
});

test('retry retrieves a committed assignment after its real HTTP response is dropped', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page, { expectedFailedRequest: /\/api\/exceptions\/[^/]+\/assign$/ });
  await login(page, 'harbor');
  const detail = await openRecord(page, 'HS-2057');
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  const attempts: { key: string | undefined; body: string | null }[] = [];
  let committedStatus: number | undefined;
  await page.route('**/api/exceptions/*/assign', async route => {
    const request = route.request();
    attempts.push({ key: request.headers()['idempotency-key'], body: request.postData() });
    if (attempts.length === 1) {
      // Send the request to the actual server and wait for its committed response.
      // Only the delivery back to this browser is discarded.
      const committed = await route.fetch();
      committedStatus = committed.status();
      await route.abort('failed');
    } else {
      await route.continue();
    }
  });
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Robin Ellis' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeVisible();
  expect(committedStatus).toBe(200);
  await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toBeDisabled();
  const recordId = new URL(page.url()).hash.split('/')[1];
  const beforeRetryResponse = await page.request.get(`/api/exceptions/${recordId}`);
  expect(beforeRetryResponse.status()).toBe(200);
  const beforeRetry = await beforeRetryResponse.json();
  expect(beforeRetry.exception.version).toBe(2);
  expect(beforeRetry.events).toHaveLength(1);
  await page.getByRole('button', { name: 'Retry same change', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Assignment saved.');
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  const afterRetryResponse = await page.request.get(`/api/exceptions/${recordId}`);
  expect(afterRetryResponse.status()).toBe(200);
  const afterRetry = await afterRetryResponse.json();
  expect(afterRetry.exception.version).toBe(2);
  expect(afterRetry.events).toHaveLength(1);
  assertBrowser();
});

test('a late refresh response cannot replace the record selected by browser navigation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  const detail = await openRecord(page, 'NL-1091');
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  const oldId = new URL(page.url()).hash.split('/')[1];
  const resolvedButton = page.getByRole('button', { name: /NL-1042/ });
  const resolvedRecord = await page.request.get('/api/exceptions');
  expect(resolvedRecord.status()).toBe(200);
  const resolvedId = (await resolvedRecord.json()).items.find((item: { reference: string }) => item.reference === 'NL-1042').id;
  await expect(resolvedButton).toBeVisible();

  let releaseResponse!: () => void;
  const release = new Promise<void>(resolve => { releaseResponse = resolve; });
  let reportHeld!: () => void;
  const held = new Promise<void>(resolve => { reportHeld = resolve; });
  await page.route(`**/api/exceptions/${oldId}`, async route => {
    const actual = await route.fetch();
    reportHeld();
    await release;
    await route.fulfill({ response: actual });
  });
  await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
  await held;
  // A browser history change can occur while refresh has disabled queue buttons.
  await page.evaluate(id => { window.location.hash = `exception/${id}`; }, resolvedId);
  await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-1042');
  await expect(detail.locator('.resolution-text')).toBeVisible();
  releaseResponse();
  // This notice appears after the held refresh completes, so the assertions below
  // observe the late result rather than winning a race against its delivery.
  await expect(page.locator('.workspace-messages').getByRole('status')).toContainText('Showing the first queue page and the latest saved record');
  await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-1042');
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(page.getByLabel('Assigned to', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Confirm resolution', exact: true })).toHaveCount(0);
  await expect(detail.locator('.history-list li')).toHaveCount(2);
  assertBrowser();
});

test('a JSON server error after commit preserves the original retry key and body', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page, { expectedStatus: 500 });
  await login(page, 'harbor');
  const detail = await openRecord(page, 'HS-2073');
  // The installed consumer assigned this record to Jules before browser acceptance.
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  const attempts: { key: string | undefined; body: string | null }[] = [];
  let committedStatus: number | undefined;
  await page.route('**/api/exceptions/*/assign', async route => {
    const request = route.request();
    attempts.push({ key: request.headers()['idempotency-key'], body: request.postData() });
    if (attempts.length === 1) {
      const committed = await route.fetch();
      committedStatus = committed.status();
      // The server transaction is real. Only its browser-facing response is
      // replaced, reproducing a gateway error after the database commit.
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({
        error: { code: 'gateway_error', message: 'The response was interrupted after forwarding.' },
      }) });
    } else {
      await route.continue();
    }
  });
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Robin Ellis' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeVisible();
  expect(committedStatus).toBe(200);
  await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toBeDisabled();
  const recordId = new URL(page.url()).hash.split('/')[1];
  const beforeRetryResponse = await page.request.get(`/api/exceptions/${recordId}`);
  expect(beforeRetryResponse.status()).toBe(200);
  const beforeRetry = await beforeRetryResponse.json();
  expect(beforeRetry.exception.version).toBe(3);
  expect(beforeRetry.events).toHaveLength(2);
  await page.getByRole('button', { name: 'Retry same change', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Assignment saved.');
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(2);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  const afterRetryResponse = await page.request.get(`/api/exceptions/${recordId}`);
  expect(afterRetryResponse.status()).toBe(200);
  const afterRetry = await afterRetryResponse.json();
  expect(afterRetry.exception.version).toBe(3);
  expect(afterRetry.events).toHaveLength(2);
  assertBrowser();
});

test('an old list refresh cannot invalidate the new selection while its detail response is pending', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  const detail = await openRecord(page, 'NL-1091');
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  const listResponse = await page.request.get('/api/exceptions');
  expect(listResponse.status()).toBe(200);
  const nextId = (await listResponse.json()).items.find((item: { reference: string }) => item.reference === 'NL-1042').id;

  let releaseList!: () => void;
  const listGate = new Promise<void>(resolve => { releaseList = resolve; });
  let reportListHeld!: () => void;
  const listHeld = new Promise<void>(resolve => { reportListHeld = resolve; });
  let releaseNextDetail!: () => void;
  const detailGate = new Promise<void>(resolve => { releaseNextDetail = resolve; });
  let reportDetailHeld!: () => void;
  const detailHeld = new Promise<void>(resolve => { reportDetailHeld = resolve; });

  await page.route(url => url.pathname === '/api/exceptions', async route => {
    if (route.request().method() !== 'GET') { await route.continue(); return; }
    const actual = await route.fetch();
    reportListHeld();
    await listGate;
    await route.fulfill({ response: actual });
  });
  await page.route(`**/api/exceptions/${nextId}`, async route => {
    const actual = await route.fetch();
    reportDetailHeld();
    await detailGate;
    await route.fulfill({ response: actual });
  });

  try {
    await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    await listHeld;
    await page.evaluate(id => { window.location.hash = `exception/${id}`; }, nextId);
    await detailHeld;
    // The old refresh resumes while the new record's real detail response is
    // still held. Its stale continuation must not invalidate that newer request.
    releaseList();
    await expect(page.locator('.workspace-messages').getByRole('status')).toContainText('Showing the first queue page and the latest saved record');
    releaseNextDetail();
    await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-1042');
    await expect(detail.locator('.record-meta')).toContainText('Version 3');
    await expect(detail.locator('.history-list li')).toHaveCount(2);
    await expect(detail.getByRole('heading', { name: 'Record unavailable', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Assigned to', { exact: true })).toBeDisabled();
    assertBrowser();
  } finally {
    // Promise resolution is safe to repeat and lets intercepted requests finish
    // even when an assertion fails before either response is released.
    releaseList();
    releaseNextDetail();
    await page.unrouteAll({ behavior: 'wait' });
  }
});

async function fillIntake(page: Page, reference: string, summary: string, details: string, priority: 'normal' | 'high' = 'normal') {
  await page.getByRole('button', { name: 'New exception', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'New shipment exception', exact: true })).toBeVisible();
  await page.getByLabel('Shipment reference', { exact: true }).fill(reference);
  await page.getByLabel('Summary', { exact: true }).fill(summary);
  await page.getByLabel('Exception details', { exact: true }).fill(details);
  await page.getByLabel('Priority', { exact: true }).selectOption(priority);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveJSProperty('translate', false);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveValue(reference);
  await expect(page.locator('label[for="new-reference"]')).toHaveJSProperty('translate', true);
  await expect(page.locator('#reference-help')).toHaveJSProperty('translate', true);
  await expect(page.locator('#reference-help')).toHaveText('References are case-sensitive and must be unique within your organization.');
  await expect(page.getByLabel('Summary', { exact: true })).toHaveJSProperty('translate', true);
  await expect(page.getByLabel('Summary', { exact: true })).toHaveValue(summary);
  await expect(page.getByLabel('Exception details', { exact: true })).toHaveJSProperty('translate', true);
  await expect(page.getByLabel('Exception details', { exact: true })).toHaveValue(details);
}

async function expectCreatedRecord(page: Page, reference: string) {
  const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
  await expect(detail.locator('.detail-heading .reference')).toHaveJSProperty('translate', false);
  await expect(detail.locator('.detail-heading h2')).toHaveJSProperty('translate', true);
  await expect(detail.locator('.detail-description p')).toHaveJSProperty('translate', true);
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  await expect(detail.locator('.history-list')).toContainText('Alex Morgan created the exception');
  expect(new URL(page.url()).hash).toMatch(/^#exception\/[0-9a-f-]{36}$/i);
  return detail;
}

test('desktop manual intake creates, assigns, resolves and reloads an exception with its creation history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  const reference = 'NL-UI-Desktop';
  const summary = 'Appointment paperwork needs review';
  const details = 'The synthetic intake packet is missing the receiving appointment.\nConfirm the appointment before the next handoff.';
  const requests: { key: string | undefined; body: Record<string, unknown> }[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/exceptions') {
      requests.push({ key: request.headers()['idempotency-key'], body: request.postDataJSON() });
    }
  });
  await fillIntake(page, `  ${reference}  `, `  ${summary}  `, `  ${details}  `, 'high');
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveAttribute('maxlength', '80');
  await expect(page.getByLabel('Summary', { exact: true })).toHaveAttribute('maxlength', '200');
  await expect(page.getByLabel('Exception details', { exact: true })).toHaveAttribute('maxlength', '4000');
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  const detail = await expectCreatedRecord(page, reference);
  await expect(detail.getByRole('heading', { name: summary, exact: true })).toBeVisible();
  await expect(detail.locator('.detail-description p')).toHaveText(details);
  await expect(detail.locator('.record-meta')).toContainText('High priority');
  expect(requests).toHaveLength(1);
  expect(requests[0].key).toMatch(/^[0-9a-f-]{36}$/i);
  expect(requests[0].body).toEqual({ reference, summary, details, priority: 'high' });
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  const note = 'Receiving confirmed the appointment and the revised synthetic packet is ready for handoff.';
  await page.getByLabel('Resolution note', { exact: true }).fill(note);
  await page.getByRole('button', { name: 'Confirm resolution', exact: true }).click();
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(3);
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'desktop-intake-resolved.png');
  await page.reload();
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(3);
  await expect(detail.locator('.history-list')).toContainText('Alex Morgan created the exception');
  assertBrowser();
});

test('mobile manual intake can be canceled, reopened, assigned and resolved without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  await fillIntake(page, 'NL-UI-Canceled', 'Unsent draft', 'This synthetic draft will be canceled.');
  await assertNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Cancel intake', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your organization', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /NL-UI-Canceled/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'New exception', exact: true }).click();
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Summary', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Exception details', { exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Create exception', exact: true })).toBeDisabled();
  const reference = 'NL-UI-Mobile';
  await page.getByLabel('Shipment reference', { exact: true }).fill(reference);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveValue(reference);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveJSProperty('translate', false);
  await page.getByLabel('Summary', { exact: true }).fill('Delivery contact needs confirmation');
  await page.getByLabel('Exception details', { exact: true }).fill('The synthetic handoff lacks a receiving contact. Confirm the contact before dispatch.');
  await assertNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  const detail = await expectCreatedRecord(page, reference);
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  const note = 'The receiving contact is confirmed in the synthetic handoff packet.';
  await page.getByLabel('Resolution note', { exact: true }).fill(note);
  await page.getByRole('button', { name: 'Confirm resolution', exact: true }).click();
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  await expect(detail.locator('.record-meta')).toContainText('Version 3');
  await expect(detail.locator('.history-list li')).toHaveCount(3);
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'mobile-intake-resolved.png');
  await page.getByRole('button', { name: 'Back to exceptions', exact: true }).click();
  await expect(page.getByRole('button', { name: new RegExp(reference) })).toBeVisible();
  await openRecord(page, reference);
  await expect(detail.locator('.resolution-text')).toHaveText(note);
  assertBrowser();
});

test('intake preparation failure and reference conflict leave a corrected intent editable with a new key', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page, { expectedStatus: 409 });
  await login(page);
  const summary = 'Synthetic duplicate reference review';
  const details = 'The reference will be corrected after the existing record is identified.';
  await fillIntake(page, 'NL-1042', summary, details);
  const attempts: { key: string | undefined; body: Record<string, unknown> }[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/exceptions') {
      attempts.push({ key: request.headers()['idempotency-key'], body: request.postDataJSON() });
    }
  });
  await page.evaluate(() => {
    Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => { throw new Error('Synthetic preparation failure'); } });
  });
  try {
    await page.getByRole('button', { name: 'Create exception', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Nothing was sent. Try again.');
    await expect(page.getByRole('button', { name: 'Create exception', exact: true })).toBeEnabled();
    await expect(page.getByLabel('Shipment reference', { exact: true })).toBeEditable();
    expect(attempts).toHaveLength(0);
  } finally {
    await page.evaluate(() => { Reflect.deleteProperty(crypto, 'randomUUID'); });
  }
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('That reference is already used in your organization');
  await expect(page.getByLabel('Shipment reference', { exact: true })).toHaveValue('NL-1042');
  await expect(page.getByLabel('Summary', { exact: true })).toHaveValue(summary);
  await expect(page.getByLabel('Exception details', { exact: true })).toHaveValue(details);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toBeEditable();
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
  const corrected = 'NL-UI-Corrected';
  await page.getByLabel('Shipment reference', { exact: true }).fill(corrected);
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  await expectCreatedRecord(page, corrected);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].body.reference).toBe('NL-1042');
  expect(attempts[1].body.reference).toBe(corrected);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1].key).not.toBe(attempts[0].key);
  const listResponse = await page.request.get('/api/exceptions');
  expect(listResponse.status()).toBe(200);
  const list = (await listResponse.json()).items;
  expect(list.filter((item: { reference: string }) => item.reference === 'NL-1042')).toHaveLength(1);
  expect(list.filter((item: { reference: string }) => item.reference === corrected)).toHaveLength(1);
  assertBrowser();
});

async function createAfterUncertainResponse(page: Page, mode: 'abort' | 'json500' | 'malformed201' | 'wrong201') {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page, mode === 'abort'
    ? { expectedFailedRequest: /^\/api\/exceptions$/ } : mode === 'json500' ? { expectedStatus: 500 } : {});
  await login(page);
  const reference = { abort: 'NL-UI-Retry-Dropped', json500: 'NL-UI-Retry-Server',
    malformed201: 'NL-UI-Retry-Malformed', wrong201: 'NL-UI-Retry-Mismatched' }[mode];
  await fillIntake(page, reference, 'Synthetic retry acceptance', 'The real server creates this record before its response is interrupted.');
  const attempts: { key: string | undefined; url: string; body: string | null }[] = [];
  let created: { id: string; reference: string } | undefined;
  let committedStatus: number | undefined;
  await page.route(url => url.pathname === '/api/exceptions', async route => {
    const request = route.request();
    if (request.method() !== 'POST') { await route.continue(); return; }
    attempts.push({ key: request.headers()['idempotency-key'], url: request.url(), body: request.postData() });
    if (attempts.length === 1) {
      const response = await route.fetch();
      committedStatus = response.status();
      created = (await response.json()).exception;
      if (mode === 'abort') {
        await route.abort('failed');
      } else if (mode === 'json500') {
        await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({
          error: { code: 'gateway_error', message: 'Synthetic response failure after forwarding.' },
        }) });
      } else if (mode === 'malformed201') {
        await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
          exception: { id: created!.id, version: 1 },
        }) });
      } else {
        await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
          exception: { ...created, id: '00000000-0000-4000-8000-00000000f00d',
            reference: 'NL-UI-Unrelated-Receipt', summary: 'A different synthetic intent' },
        }) });
      }
    } else { await route.continue(); }
  });
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeVisible();
  expect(committedStatus).toBe(201);
  expect(created?.reference).toBe(reference);
  await expect(page.getByLabel('Shipment reference', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Exception details', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Create exception', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cancel intake', exact: true })).toBeDisabled();
  const beforeResponse = await page.request.get(`/api/exceptions/${created!.id}`);
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  expect(before.exception.version).toBe(1);
  expect(before.events).toHaveLength(1);
  expect(before.events[0].action).toBe('created');
  await page.getByRole('button', { name: 'Retry same change', exact: true }).click();
  const detail = await expectCreatedRecord(page, reference);
  expect(new URL(page.url()).hash).toBe(`#exception/${created!.id}`);
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  const listResponse = await page.request.get('/api/exceptions');
  expect(listResponse.status()).toBe(200);
  const matching = (await listResponse.json()).items.filter((item: { reference: string }) => item.reference === reference);
  expect(matching).toHaveLength(1);
  expect(matching[0].id).toBe(created!.id);
  const afterResponse = await page.request.get(`/api/exceptions/${created!.id}`);
  expect(afterResponse.status()).toBe(200);
  const after = await afterResponse.json();
  expect(after.exception.version).toBe(1);
  expect(after.events).toHaveLength(1);
  expect(after.events[0].action).toBe('created');
  assertBrowser();
}

test('intake retries an actually committed creation after its HTTP response is dropped', async ({ page }) => {
  await createAfterUncertainResponse(page, 'abort');
});

test('intake retries an actually committed creation after a JSON server error with the same key and body', async ({ page }) => {
  await createAfterUncertainResponse(page, 'json500');
});

for (const [mode, label] of [
  ['malformed201', 'a malformed 201 creation representation'],
  ['wrong201', 'a 201 representation with an unrelated UUID and body'],
] as const) {
  test(`intake preserves the retry intent after ${label}`, async ({ page }) => {
    await createAfterUncertainResponse(page, mode);
  });
}

function loginAdmissionFixture(command: 'exhaust' | 'expire') {
  const python = process.env.WORKSPACE_FIXTURE_PYTHON;
  if (!python || !process.env.WORKSPACE_LOGIN_FIXTURE_URL) {
    throw new Error('The scoped login-admission fixture environment must be set explicitly.');
  }
  const result = spawnSync(python, ['../tools/browser_login_fixture.py', command], {
    cwd: process.cwd(), env: process.env, encoding: 'utf8', windowsHide: true,
    timeout: 10_000, maxBuffer: 64 * 1024,
  });
  // Child diagnostics can contain a connection URL. Only validated, nonsensitive
  // acknowledgement fields are accepted or reported to the test runner.
  if (result.error || result.status !== 0) {
    throw new Error(`Login-admission fixture ${command} failed (exit ${result.status ?? 'unavailable'}).`);
  }
  let acknowledgement;
  try { acknowledgement = JSON.parse(result.stdout.trim()); }
  catch { throw new Error(`Login-admission fixture ${command} did not return a valid acknowledgement.`); }
  if (acknowledgement?.command !== command || acknowledgement?.ok !== true) {
    throw new Error(`Login-admission fixture ${command} did not confirm the requested operation.`);
  }
}

async function prepareSignIn(page: Page, password = demoPassword!) {
  await page.goto('/');
  const email = page.getByLabel('Email address', { exact: true });
  const passwordInput = page.getByLabel('Password', { exact: true });
  await expect(email).toBeVisible();
  await email.focus();
  await page.keyboard.press('Tab');
  await expect(passwordInput).toBeFocused();
  await email.fill('alex@northline.example');
  await passwordInput.fill(password);
  return { email, password: passwordInput, submit: page.getByRole('button', { name: 'Sign in', exact: true }) };
}

async function expectAnonymousSession(page: Page) {
  const response = await page.request.get('/api/session');
  expect(response.status()).toBe(200);
  expect((await response.json()).authenticated).toBe(false);
}

for (const viewport of [
  { label: 'desktop', width: 1440, height: 1000 },
  { label: 'narrow', width: 390, height: 844 },
] as const) {
  test(`real login admission throttles ${viewport.label} sign-in until fixture expiry and an explicit manual retry`, async ({ page }) => {
    test.info().annotations.push({ type: 'evidence', description: 'Actual PostgreSQL admission and real 429. Server windows expire through a scoped SQL fixture. Only isolated browser time is advanced, not a real 60 second wait or the server clock.' });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    // Playwright clock emulation must be installed before the application's
    // performance clock or timers are used. It does not change PostgreSQL time.
    await page.clock.install();
    const assertBrowser = observeBrowser(page, { expectedStatus: 429 });
    let loginPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/login') loginPosts++;
    });
    loginAdmissionFixture('exhaust');
    try {
      const form = await prepareSignIn(page);
      const firstResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/login');
      await form.submit.click();
      const throttled = await firstResponse;
      expect(throttled.status()).toBe(429);
      const retryAfter = throttled.headers()['retry-after'];
      expect(retryAfter).toMatch(/^\d+$/);
      expect(Number(retryAfter)).toBeGreaterThanOrEqual(1);
      expect(Number(retryAfter)).toBeLessThanOrEqual(60);
      const error = (await throttled.json()).error;
      expect(error.code).toBe('login_throttled');
      expect(error.message).toBe('Too many sign-in attempts. Wait before trying again.');
      await expect(page.getByRole('alert')).toHaveText(error.message);
      await expect(page.locator('#login-wait')).toContainText('Try again in');
      await expect(page.locator('#login-wait')).toContainText('The server decides when sign-in is allowed.');
      await expect(form.submit).toBeDisabled();
      await expect(form.email).toBeEditable();
      await expect(form.password).toBeEditable();
      await expectAnonymousSession(page);
      await form.password.press('Enter');
      await page.clock.runFor(1000);
      expect(loginPosts).toBe(1);
      await form.email.fill('sam@northline.example');
      await expect(form.submit).toBeDisabled();
      await form.email.fill('alex@northline.example');
      await assertNoHorizontalOverflow(page);
      await screenshot(page, `${viewport.label}-login-throttled.png`);

      // Actual server recovery comes from the scoped database fixture. Advancing
      // the browser clock only releases the local reminder and submit control.
      loginAdmissionFixture('expire');
      await page.clock.fastForward(61_000);
      await expect(page.locator('#login-wait')).toContainText('The countdown has ended.');
      await expect(form.submit).toBeEnabled();
      expect(loginPosts).toBe(1);
      await expectAnonymousSession(page);
      await form.submit.click();
      await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
      await expect(page.locator('.identity')).toContainText('Northline Logistics');
      expect(loginPosts).toBe(2);
      const authenticated = await page.request.get('/api/session');
      expect(authenticated.status()).toBe(200);
      const session = await authenticated.json();
      expect(session.authenticated).toBe(true);
      expect(session.user.email).toBe('alex@northline.example');
      await assertNoHorizontalOverflow(page);
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
      await expect(page.locator('#login-wait')).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
      assertBrowser();
    } finally {
      loginAdmissionFixture('expire');
    }
  });
}

test('a malformed Retry-After response fixture allows honest manual recovery without automatic login', async ({ page }) => {
  test.info().annotations.push({ type: 'fixture-only', description: 'The real server rejects a wrong password with 401. Only its browser-facing response is substituted with 429 and a malformed Retry-After header to test client recovery.' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.clock.install();
  const assertBrowser = observeBrowser(page, { expectedStatus: 429 });
  let loginPosts = 0;
  let interceptedAttempts = 0;
  let originalStatus: number | undefined;
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/login') loginPosts++;
  });
  loginAdmissionFixture('expire');
  try {
    await page.route('**/api/login', async route => {
      interceptedAttempts++;
      if (interceptedAttempts === 1) {
        const actual = await route.fetch();
        originalStatus = actual.status();
        await route.fulfill({ status: 429, contentType: 'application/json', headers: { 'Retry-After': 'not-a-delay' },
          body: JSON.stringify({ error: { code: 'login_throttled', message: 'Too many sign-in attempts. Wait before trying again.' } }) });
      } else { await route.continue(); }
    });
    const form = await prepareSignIn(page, `${demoPassword!}-invalid`);
    await form.submit.click();
    await expect(page.locator('#login-wait')).toContainText('The server did not provide a usable retry time.');
    expect(originalStatus).toBe(401);
    await expect(form.submit).toBeEnabled();
    await expect(form.password).toBeEditable();
    await expectAnonymousSession(page);
    await page.clock.fastForward(61_000);
    expect(loginPosts).toBe(1);
    await expectAnonymousSession(page);
    await assertNoHorizontalOverflow(page);
    await form.password.fill(demoPassword!);
    await form.submit.click();
    await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
    await expect(page.locator('.identity')).toContainText('Northline Logistics');
    expect(loginPosts).toBe(2);
    assertBrowser();
  } finally {
    loginAdmissionFixture('expire');
  }
});

function queueFixture() {
  const python = process.env.WORKSPACE_FIXTURE_PYTHON;
  if (!python || !process.env.WORKSPACE_QUEUE_FIXTURE_URL) {
    throw new Error('The scoped queue fixture environment must be set explicitly.');
  }
  const result = spawnSync(python, ['../tools/browser_queue_fixture.py'], {
    cwd: process.cwd(), env: process.env, encoding: 'utf8', windowsHide: true,
    timeout: 10_000, maxBuffer: 64 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Queue fixture failed (exit ${result.status ?? 'unavailable'}).`);
  }
  let acknowledgement;
  try { acknowledgement = JSON.parse(result.stdout.trim()); }
  catch { throw new Error('Queue fixture did not return a valid acknowledgement.'); }
  if (acknowledgement?.command !== 'seed' || acknowledgement?.ok !== true ||
      acknowledgement?.northline !== 54 || acknowledgement?.harbor !== 4) {
    throw new Error('Queue fixture did not confirm the expected synthetic records.');
  }
}

async function expectQueuePage(page: Page, number: number, count?: number) {
  const queue = page.locator('.queue-panel');
  await expect(queue.locator('.panel-heading p')).toContainText(`on this page / Page ${number}`);
  await expect(queue.locator('.queue-error')).toHaveCount(0);
  if (count !== undefined) await expect(queue.locator('.exception-row')).toHaveCount(count);
  return queue;
}

async function submitQueueSearch(page: Page, q: string) {
  await page.getByLabel('Search references and summaries', { exact: true }).fill(q);
  await page.getByRole('button', { name: 'Search queue', exact: true }).click();
}

async function searchQueue(page: Page, q: string, count?: number) {
  await submitQueueSearch(page, q);
  const queue = await expectQueuePage(page, 1, count);
  if (q.trim()) await expect(queue.locator('.queue-query')).toContainText(q.trim());
  return queue;
}

async function queueReferences(page: Page) {
  return page.locator('.queue-panel .exception-row .reference').allTextContents();
}

async function settleDeliveredQueueResponse(page: Page, response: Response) {
  expect(await response.finished(), 'The held queue response completed delivery').toBeNull();
  // Observe the delivered response and subsequent rendering, rather than
  // asserting the new page before the deliberately late response arrives.
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

test('desktop queue traverses all unchanged fixture rows before filtering and resolving an off-page selection', async ({ page }) => {
  queueFixture();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  const queue = await searchQueue(page, 'Queue browse', 20);
  await expect(page.getByRole('button', { name: 'Previous page', exact: true })).toBeDisabled();
  const references = await queueReferences(page);
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 2, 20);
  references.push(...await queueReferences(page));
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 3, 14);
  references.push(...await queueReferences(page));
  expect(references).toEqual(Array.from({ length: 54 }, (_, index) => `NL-Q-${index.toString().padStart(3, '0')}`));
  expect(new Set(references).size).toBe(54);
  expect(references.some(reference => reference.startsWith('HS-'))).toBe(false);
  await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Previous page', exact: true }).click();
  await expectQueuePage(page, 2, 20);
  expect(await queueReferences(page)).toEqual(references.slice(20, 40));
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'desktop-queue-page-two.png');

  await page.getByLabel('Show exceptions', { exact: true }).selectOption('resolved');
  await expectQueuePage(page, 1, 18);
  await expect(queue.locator('.exception-row .status')).toHaveText(Array(18).fill('Resolved'));
  await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
  await page.getByLabel('Show exceptions', { exact: true }).selectOption('open');
  await expectQueuePage(page, 1, 20);
  await expect(queue.locator('.exception-row .status')).toHaveText(Array(20).fill('Open'));
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 2, 16);
  const detail = await openRecord(page, 'NL-Q-053');
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  await page.getByLabel('Resolution note', { exact: true }).fill('Synthetic queue browsing acceptance completed the handoff.');
  await page.getByRole('button', { name: 'Confirm resolution', exact: true }).click();
  await expect(detail.locator('.record-meta')).toContainText('Version 2');
  await expectQueuePage(page, 1, 20);
  await expect(page.getByLabel('Show exceptions', { exact: true })).toHaveValue('open');
  await expect(page.getByLabel('Search references and summaries', { exact: true })).toHaveValue('Queue browse');
  await expect(queue.getByRole('button', { name: /NL-Q-053/ })).toHaveCount(0);
  await expect(detail.locator('.queue-selection-note')).toBeVisible();
  await expect(detail.locator('.resolution-text')).toContainText('Synthetic queue browsing acceptance');
  await expect(detail.locator('.history-list li')).toHaveCount(1);
  assertBrowser();
});

test('narrow queue keeps literal search, empty recovery, live paging and off-page details usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  const queue = await searchQueue(page, '%_!', 1);
  expect(await queueReferences(page)).toEqual(['NL-Q-052']);
  await expect(queue.locator('.exception-row > strong')).toHaveText('Queue browse 100%_! literal marker');
  await assertNoHorizontalOverflow(page);
  await screenshot(page, 'mobile-queue-literal.png');
  await page.getByLabel('Show exceptions', { exact: true }).selectOption('resolved');
  await expectQueuePage(page, 1, 0);
  await searchQueue(page, 'No-such-synthetic-queue-entry', 0);
  await expect(queue.getByText('No exceptions match this search and status on this page.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Clear search', exact: true }).click();
  await expectQueuePage(page, 1, 20);
  await expect(page.getByLabel('Search references and summaries', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Show exceptions', { exact: true })).toHaveValue('resolved');
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 2);
  const reference = (await queueReferences(page))[0];
  expect(reference).toBeTruthy();
  await expect(queue.locator('.exception-row .status')).toHaveText(Array((await queueReferences(page)).length).fill('Resolved'));
  const detail = await openRecord(page, reference);
  await expect(queue).not.toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
  await expectQueuePage(page, 1, 20);
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
  await expect(detail.locator('.queue-selection-note')).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Back to exceptions', exact: true }).click();
  await expect(queue).toBeVisible();
  await searchQueue(page, '<script>', 1);
  await expect(queue.locator('.exception-row > strong')).toHaveText('Queue browse <script>literal markup</script>');
  await expect(queue.locator('.exception-row script')).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  assertBrowser();
});

test('late queue query success and a substituted page error cannot replace a newer search', async ({ page }) => {
  test.info().annotations.push({ type: 'response-fixture', description: 'Actual PostgreSQL GET responses are held. One successful older page is replaced with a browser-facing 500 after a newer query has completed.' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page, { expectedStatus: 500 });
  await login(page);
  let releaseQuery = () => {};
  let releasePage = () => {};
  const queryRoute = (url: URL) => url.pathname === '/api/exceptions' && url.searchParams.get('q') === 'Queue browse' && !url.searchParams.has('cursor');
  const pageRoute = (url: URL) => url.pathname === '/api/exceptions' && url.searchParams.get('q') === 'Queue browse' && url.searchParams.has('cursor');
  try {
    let queryHeld!: () => void;
    const heldQuery = new Promise<void>(resolve => { queryHeld = resolve; });
    const queryGate = new Promise<void>(resolve => { releaseQuery = resolve; });
    let oldQueryReference: string | undefined;
    await page.route(queryRoute, async route => {
      const actual = await route.fetch();
      expect(actual.status()).toBe(200);
      oldQueryReference = (await actual.json()).items[0].reference;
      queryHeld();
      await queryGate;
      await route.fulfill({ response: actual });
    });
    await submitQueueSearch(page, 'Queue browse');
    await heldQuery;
    expect(oldQueryReference).toBe('NL-Q-000');
    await searchQueue(page, '%_!', 1);
    expect(await queueReferences(page)).toEqual(['NL-Q-052']);
    const deliveredQuery = page.waitForResponse(response => response.request().method() === 'GET' && queryRoute(new URL(response.url())));
    releaseQuery();
    await settleDeliveredQueueResponse(page, await deliveredQuery);
    await expectQueuePage(page, 1, 1);
    expect(await queueReferences(page)).toEqual(['NL-Q-052']);
    await expect(page.locator('.queue-query')).toContainText('%_!');
    await page.unroute(queryRoute);

    await searchQueue(page, 'Queue browse', 20);
    let pageHeld!: () => void;
    const heldPage = new Promise<void>(resolve => { pageHeld = resolve; });
    const pageGate = new Promise<void>(resolve => { releasePage = resolve; });
    let actualPageReference: string | undefined;
    await page.route(pageRoute, async route => {
      const actual = await route.fetch();
      expect(actual.status()).toBe(200);
      actualPageReference = (await actual.json()).items[0].reference;
      pageHeld();
      await pageGate;
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_page_error', message: 'Controlled old-page response failure.' } }) });
    });
    await page.getByRole('button', { name: 'Next page', exact: true }).click();
    await heldPage;
    expect(actualPageReference).toBe('NL-Q-020');
    await searchQueue(page, 'No-current-queue-match', 0);
    const deliveredError = page.waitForResponse(response => response.request().method() === 'GET' && pageRoute(new URL(response.url())) && response.status() === 500);
    releasePage();
    await settleDeliveredQueueResponse(page, await deliveredError);
    await expectQueuePage(page, 1, 0);
    await expect(page.locator('.queue-query')).toContainText('No-current-queue-match');
    await expect(page.getByRole('alert')).toHaveCount(0);
    assertBrowser();
  } finally {
    releaseQuery(); releasePage();
    await page.unrouteAll({ behavior: 'wait' });
  }
});

test('later-page creation resets browsing, survives its off-page bookmark and clears private queue state on organization switch', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assertBrowser = observeBrowser(page);
  await login(page);
  await searchQueue(page, 'Queue browse', 20);
  await page.getByLabel('Show exceptions', { exact: true }).selectOption('open');
  await expectQueuePage(page, 1, 20);
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 2, 15);
  await fillIntake(page, 'NL-ZQ-Created', 'Created during bounded browsing', 'Synthetic intake from a later queue page.');
  await page.getByRole('button', { name: 'Create exception', exact: true }).click();
  const detail = await expectCreatedRecord(page, 'NL-ZQ-Created');
  const createdHash = new URL(page.url()).hash;
  await expectQueuePage(page, 1, 20);
  await expect(page.getByLabel('Search references and summaries', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Show exceptions', { exact: true })).toHaveValue('all');
  await expect(page.locator('.queue-query')).toHaveCount(0);
  await expect(page.locator('.queue-panel').getByRole('button', { name: /NL-ZQ-Created/ })).toHaveCount(0);
  await expect(detail.locator('.queue-selection-note')).toBeVisible();
  await page.reload();
  await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-ZQ-Created');
  expect(new URL(page.url()).hash).toBe(createdHash);
  await expectQueuePage(page, 1, 20);
  await expect(detail.locator('.queue-selection-note')).toBeVisible();

  await page.evaluate(() => { window.location.hash = ''; });
  await searchQueue(page, 'Queue browse', 20);
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expectQueuePage(page, 2, 20);
  let releaseOld = () => {};
  let reportHeld!: () => void;
  const held = new Promise<void>(resolve => { reportHeld = resolve; });
  const gate = new Promise<void>(resolve => { releaseOld = resolve; });
  const oldRoute = (url: URL) => url.pathname === '/api/exceptions' && url.searchParams.get('q') === 'Queue browse' && !url.searchParams.has('cursor');
  await page.route(oldRoute, async route => {
    const actual = await route.fetch();
    expect(actual.status()).toBe(200);
    expect((await actual.json()).items[0].reference).toBe('NL-Q-000');
    reportHeld();
    await gate;
    await route.fulfill({ response: actual });
  });
  try {
    await submitQueueSearch(page, 'Queue browse');
    await held;
    await page.getByLabel('Search references and summaries', { exact: true }).fill('Unsent Northline draft');
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    // Stay in the same document so the held Northline response can actually
    // arrive after Harbor takes ownership of the page.
    await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
    await page.getByLabel('Email address', { exact: true }).fill('jules@harbor.example');
    await page.getByLabel('Password', { exact: true }).fill(demoPassword!);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.locator('.identity')).toContainText('Harbor Supply');
    await expectQueuePage(page, 1, 7);
    await expect(page.getByLabel('Search references and summaries', { exact: true })).toHaveValue('');
    await expect(page.getByLabel('Show exceptions', { exact: true })).toHaveValue('all');
    await expect(page.getByRole('button', { name: 'Previous page', exact: true })).toBeDisabled();
    await expect(page.locator('.queue-query')).toHaveCount(0);
    expect(new URL(page.url()).hash).toBe('');
    const deliveredOld = page.waitForResponse(response => response.request().method() === 'GET' && oldRoute(new URL(response.url())));
    test.info().annotations.push({ type: 'delivery-stage', description: 'Harbor state verified before releasing the old Northline response.' });
    releaseOld();
    const oldResponse = await deliveredOld;
    test.info().annotations.push({ type: 'delivery-stage', description: 'Old Northline response headers arrived after Harbor state.' });
    await settleDeliveredQueueResponse(page, oldResponse);
    test.info().annotations.push({ type: 'delivery-stage', description: 'Old response body finished and subsequent render frames completed.' });
    await expectQueuePage(page, 1, 7);
    expect((await queueReferences(page)).every(reference => reference.startsWith('HS-'))).toBe(true);
    await expect(page.locator('.queue-panel').getByRole('button', { name: /NL-/ })).toHaveCount(0);
    await page.unroute(oldRoute);
    await searchQueue(page, 'Queue browse', 4);
    test.info().annotations.push({ type: 'delivery-stage', description: 'Fresh Harbor search completed after the discarded old response.' });
    expect(await queueReferences(page)).toEqual(['HS-Q-000', 'HS-Q-001', 'HS-Q-002', 'HS-Q-003']);
    await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
    await assertNoHorizontalOverflow(page);
    assertBrowser();
  } finally {
    releaseOld();
    await page.unrouteAll({ behavior: 'wait' });
  }
});

function roleFixture(command: 'demote-alex' | 'promote-alex') {
  const python = process.env.WORKSPACE_FIXTURE_PYTHON;
  if (!python || !process.env.WORKSPACE_ROLE_FIXTURE_URL) {
    throw new Error('The scoped role fixture environment must be set explicitly.');
  }
  const result = spawnSync(python, ['../tools/browser_role_fixture.py', command], {
    cwd: process.cwd(), env: process.env, encoding: 'utf8', windowsHide: true,
    timeout: 10_000, maxBuffer: 64 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Role fixture ${command} failed (exit ${result.status ?? 'unavailable'}).`);
  }
  let acknowledgement;
  try { acknowledgement = JSON.parse(result.stdout.trim()); }
  catch { throw new Error('Role fixture did not return a valid acknowledgement.'); }
  if (acknowledgement?.command !== command || acknowledgement?.ok !== true ||
      acknowledgement?.role !== (command === 'demote-alex' ? 'reviewer' : 'operator')) {
    throw new Error('Role fixture did not confirm the requested synthetic actor role.');
  }
}

async function refreshWorkspaceAccess(page: Page, role: 'operator' | 'reviewer') {
  const sessionResponse = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === '/api/session');
  await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
  const response = await sessionResponse;
  expect(response.status()).toBe(200);
  expect((await response.json()).user.role).toBe(role);
  await expect(page.locator('.identity .access-role')).toHaveText(role === 'operator' ? 'Operator' : 'Read-only reviewer');
  await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  test(`${viewport.name} reviewer reads history and bounded queue pages without business mutation controls`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const assertBrowser = observeBrowser(page);
    let businessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    });
    await login(page, 'northline', 'reviewer');
    await expect(page.getByRole('region', { name: 'Read-only access', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New exception', exact: true })).toHaveCount(0);
    const detail = await openRecord(page, 'NL-1042');
    await expect(detail.locator('.history-list li')).toHaveCount(2);
    await expect(detail.locator('.resolution-text')).toBeVisible();
    await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Resolution note', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Confirm resolution', exact: true })).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
    await screenshot(page, `${viewport.name}-reviewer.png`);
    if (viewport.name === 'narrow') await page.getByRole('button', { name: 'Back to exceptions', exact: true }).click();
    await searchQueue(page, 'Queue browse', 20);
    await page.getByRole('button', { name: 'Next page', exact: true }).click();
    await expectQueuePage(page, 2, 20);
    await page.getByRole('button', { name: 'Previous page', exact: true }).click();
    await expectQueuePage(page, 1, 20);
    await page.getByLabel('Show exceptions', { exact: true }).selectOption('resolved');
    const queue = await expectQueuePage(page, 1);
    await expect(queue.locator('.exception-row')).not.toHaveCount(0);
    await expect(queue.locator('.status-open')).toHaveCount(0);
    await page.evaluate(() => { window.location.hash = 'new'; });
    await expect(page.getByRole('form', { name: 'New exception', exact: true })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'New shipment exception', exact: true })).toHaveCount(0);
    await expect.poll(() => new URL(page.url()).hash).toBe('');
    await expect(page.getByRole('heading', { name: 'Your organization', exact: true })).toBeVisible();
    await refreshWorkspaceAccess(page, 'reviewer');
    await assertNoHorizontalOverflow(page);
    expect(businessPosts).toBe(0);
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
    expect(businessPosts).toBe(0);
    assertBrowser();
  });
}

test('a stale operator is denied after demotion and explicit refresh reloads current access', async ({ page }) => {
  roleFixture('promote-alex');
  const assertBrowser = observeBrowser(page, { expectedStatus: 403 });
  try {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await login(page);
    await searchQueue(page, 'NL-Q-001', 1);
    const detail = await openRecord(page, 'NL-Q-001');
    const id = new URL(page.url()).hash.split('/')[1];
    const beforeResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(beforeResponse.status()).toBe(200);
    const before = await beforeResponse.json();
    let businessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    });
    roleFixture('demote-alex');
    // The stale page still offers a write, but the real API must refuse it.
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    const denied = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/assign'));
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    expect((await denied).status()).toBe(403);
    await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
    await expect(page.getByRole('alert')).toContainText('This attempt was denied');
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
    const afterResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(afterResponse.status()).toBe(200);
    expect(await afterResponse.json()).toEqual(before);
    expect(businessPosts).toBe(1);
    await refreshWorkspaceAccess(page, 'reviewer');
    await expect(detail.locator('.record-meta')).toContainText(`Version ${before.exception.version}`);
    roleFixture('promote-alex');
    await refreshWorkspaceAccess(page, 'operator');
    await expect(page.getByLabel('Assigned to', { exact: true })).toBeVisible();
    roleFixture('demote-alex');
    await refreshWorkspaceAccess(page, 'reviewer');
    await expect(page.getByRole('button', { name: 'New exception', exact: true })).toHaveCount(0);
    expect(businessPosts).toBe(1);
    assertBrowser();
  } finally { roleFixture('promote-alex'); }
});

test('a denied replay after an interrupted commit preserves honest read-only recovery', async ({ page }) => {
  roleFixture('promote-alex');
  const assertBrowser = observeBrowser(page, { expectedStatus: 403, expectedFailedRequest: /\/api\/exceptions\/[^/]+\/assign$/ });
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    await searchQueue(page, 'NL-Q-002', 1);
    const detail = await openRecord(page, 'NL-Q-002');
    const id = new URL(page.url()).hash.split('/')[1];
    const attempts: { key: string | undefined; body: string | null }[] = [];
    let committedStatus: number | undefined;
    await page.route(`**/api/exceptions/${id}/assign`, async route => {
      const request = route.request();
      attempts.push({ key: request.headers()['idempotency-key'], body: request.postData() });
      if (attempts.length === 1) {
        const committed = await route.fetch();
        committedStatus = committed.status();
        await route.abort('failed');
      } else { await route.continue(); }
    });
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeVisible();
    expect(committedStatus).toBe(200);
    const committedResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(committedResponse.status()).toBe(200);
    const committed = await committedResponse.json();
    expect(committed.exception.version).toBe(2);
    expect(committed.events).toHaveLength(1);
    roleFixture('demote-alex');
    const denied = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/assign'));
    await page.getByRole('button', { name: 'Retry same change', exact: true }).click();
    expect((await denied).status()).toBe(403);
    await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
    await expect(page.getByRole('alert')).toContainText('An earlier interrupted request may already be saved.');
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
    expect(attempts).toHaveLength(2);
    expect(attempts[0].key).toBeTruthy();
    expect(attempts[1]).toEqual(attempts[0]);
    const afterResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(afterResponse.status()).toBe(200);
    expect(await afterResponse.json()).toEqual(committed);
    await refreshWorkspaceAccess(page, 'reviewer');
    await expect(detail.locator('.record-meta')).toContainText('Version 2');
    await expect(detail.locator('.history-list li')).toHaveCount(1);
    await expect(detail.locator('.action-card')).toContainText(['Current owner: Sam Rivera', 'Only operators can record a resolution.']);
    await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
    expect(attempts).toHaveLength(2);
    assertBrowser();
  } finally {
    roleFixture('promote-alex');
    await page.unrouteAll({ behavior: 'wait' });
  }
});

function historyFixture(command: 'seed' | 'append') {
  const python = process.env.WORKSPACE_FIXTURE_PYTHON;
  if (!python || !process.env.WORKSPACE_HISTORY_FIXTURE_URL) {
    throw new Error('The scoped history fixture environment must be set explicitly.');
  }
  const result = spawnSync(python, ['../tools/browser_history_fixture.py', command], {
    cwd: process.cwd(), env: process.env, encoding: 'utf8', windowsHide: true,
    timeout: 10_000, maxBuffer: 64 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`History fixture ${command} failed (exit ${result.status ?? 'unavailable'}).`);
  }
  let acknowledgement;
  try { acknowledgement = JSON.parse(result.stdout.trim()); }
  catch { throw new Error('History fixture did not return a valid acknowledgement.'); }
  if (acknowledgement?.command !== command || acknowledgement?.ok !== true ||
      acknowledgement?.id !== '00000000-0000-0000-0000-000000001fa5' ||
      acknowledgement?.version !== (command === 'seed' ? 45 : 46)) {
    throw new Error('History fixture did not confirm the requested synthetic history.');
  }
}

async function historyVersions(page: Page) {
  return page.locator('.history-list .history-meta').evaluateAll(elements => elements.map(element => {
    const version = /^Version (\d+) \//.exec(element.textContent ?? '');
    return version ? Number(version[1]) : -1;
  }));
}

async function expectHistoryPage(page: Page, number: number, events: { version: number }[], throughVersion: number) {
  const history = page.getByRole('region', { name: 'Change history', exact: true });
  await expect(history.locator('.history-heading')).toContainText(`${events.length} on this page / Page ${number}`);
  await expect(history.locator('.history-list li')).toHaveCount(events.length);
  expect(await historyVersions(page)).toEqual(events.map(event => event.version));
  await expect(history.locator('.history-boundary')).toContainText(`through version ${throughVersion}.`);
  await expect(history.getByRole('navigation', { name: 'Change history pages', exact: true })).toContainText(`Page ${number}`);
  return history;
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  test(`${viewport.name} reviewer browses bounded history pages through a fixed version`, async ({ page }) => {
    if (viewport.name === 'desktop') historyFixture('seed');
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const assertBrowser = observeBrowser(page);
    let businessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    });
    await login(page, 'northline', 'reviewer');
    await searchQueue(page, 'NL-HISTORY-001', 1);
    const detail = await openRecord(page, 'NL-HISTORY-001');
    const id = new URL(page.url()).hash.split('/')[1];
    const firstResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(firstResponse.status()).toBe(200);
    const first = await firstResponse.json();
    expect(first.events).toHaveLength(20);
    const ceiling = first.history.through_version;
    const seen = [...first.events.map((event: { version: number }) => event.version)];
    await expectHistoryPage(page, 1, first.events, ceiling);
    await expect(page.getByRole('button', { name: 'Newer changes', exact: true })).toBeDisabled();
    const secondResponse = await page.request.get(`/api/exceptions/${id}/history`, { params: { limit: 20, cursor: first.history.next_cursor } });
    expect(secondResponse.status()).toBe(200);
    const second = await secondResponse.json();
    await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    await expectHistoryPage(page, 2, second.events, ceiling);
    seen.push(...second.events.map((event: { version: number }) => event.version));
    await expect(detail.locator('.record-meta')).toContainText(`Version ${first.exception.version}`);
    if (viewport.name === 'desktop') historyFixture('append');
    const thirdResponse = await page.request.get(`/api/exceptions/${id}/history`, { params: { limit: 20, cursor: second.next_cursor } });
    expect(thirdResponse.status()).toBe(200);
    const third = await thirdResponse.json();
    await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    const history = await expectHistoryPage(page, 3, third.events, ceiling);
    expect(third.through_version).toBe(ceiling);
    seen.push(...third.events.map((event: { version: number }) => event.version));
    expect(seen.length).toBe(ceiling);
    expect([...seen].sort((a, b) => a - b)).toEqual(Array.from({ length: ceiling }, (_, index) => index + 1));
    await expect(history.getByRole('button', { name: 'Older changes', exact: true })).toBeDisabled();
    await assertNoHorizontalOverflow(page);
    await screenshot(page, `${viewport.name}-history.png`);
    await page.getByRole('button', { name: 'Newer changes', exact: true }).click();
    await expectHistoryPage(page, 2, second.events, ceiling);
    await page.getByRole('button', { name: 'Newer changes', exact: true }).click();
    await expectHistoryPage(page, 1, first.events, ceiling);
    await refreshWorkspaceAccess(page, 'reviewer');
    const refreshedResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(refreshedResponse.status()).toBe(200);
    const refreshed = await refreshedResponse.json();
    await expectHistoryPage(page, 1, refreshed.events, refreshed.history.through_version);
    expect(refreshed.history.through_version).toBe(46);
    await expect(detail.locator('.record-meta')).toContainText('Version 46');
    await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
    expect(businessPosts).toBe(0);
    assertBrowser();
  });
}

test('history failure retries preserve the current record and draft, then a saved mutation resets history', async ({ page }) => {
  const assertBrowser = observeBrowser(page, { expectedStatus: 503 });
  await login(page);
  await searchQueue(page, 'NL-HISTORY-001', 1);
  const detail = await openRecord(page, 'NL-HISTORY-001');
  const id = new URL(page.url()).hash.split('/')[1];
  const beforeResponse = await page.request.get(`/api/exceptions/${id}`);
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  const draft = 'Draft retained while reading an older history page.';
  await page.getByLabel('Resolution note', { exact: true }).fill(draft);
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Alex Morgan' });
  let attempts = 0;
  const routePattern = `**/api/exceptions/${id}/history?**`;
  await page.route(routePattern, async route => {
    attempts++;
    if (attempts === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_unavailable', message: 'Synthetic history failure.' } }) });
    } else { await route.continue(); }
  });
  try {
    await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    const history = page.getByRole('region', { name: 'Change history', exact: true });
    await expect(history.getByRole('alert')).toContainText('This history page could not be loaded.');
    await expect(history.locator('.history-list li')).toHaveCount(0);
    await expect(detail.locator('.record-meta')).toContainText(`Version ${before.exception.version}`);
    await expect(page.getByLabel('Resolution note', { exact: true })).toHaveValue(draft);
    await expect(page.getByLabel('Assigned to', { exact: true })).toHaveValue('00000000-0000-0000-0000-00000000000b');
    const expectedResponse = await page.request.get(`/api/exceptions/${id}/history`, { params: { limit: 20, cursor: before.history.next_cursor } });
    expect(expectedResponse.status()).toBe(200);
    const expected = await expectedResponse.json();
    await page.getByRole('button', { name: 'Retry history page', exact: true }).click();
    await expectHistoryPage(page, 2, expected.events, expected.through_version);
    await expect(page.getByLabel('Resolution note', { exact: true })).toHaveValue(draft);
    await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await expect(page.getByRole('status')).toHaveText('Assignment saved.');
    const savedResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(savedResponse.status()).toBe(200);
    const saved = await savedResponse.json();
    expect(saved.exception.version).toBe(before.exception.version + 1);
    await expectHistoryPage(page, 1, saved.events, saved.exception.version);
    await expect(detail.locator('.record-meta')).toContainText(`Version ${saved.exception.version}`);
    expect(saved.events.at(-1).action).toBe('assigned');
    expect(attempts).toBe(2);
    assertBrowser();
  } finally { await page.unrouteAll({ behavior: 'wait' }); }
});

test('delayed history is retired by record changes, refresh and logout', async ({ page }) => {
  const assertBrowser = observeBrowser(page);
  await login(page, 'northline', 'reviewer');
  await searchQueue(page, 'NL-HISTORY-001', 1);
  await openRecord(page, 'NL-HISTORY-001');
  const id = new URL(page.url()).hash.split('/')[1];
  const pattern = `**/api/exceptions/${id}/history?**`;
  async function delayOlderPage() {
    let release!: () => void;
    let acknowledge!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const arrived = new Promise<void>(resolve => { acknowledge = resolve; });
    await page.route(pattern, async route => {
      const actual = await route.fetch();
      expect(actual.status()).toBe(200);
      acknowledge();
      await gate;
      await route.fulfill({ response: actual });
    }, { times: 1 });
    await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    await arrived;
    let finished: Promise<void> | undefined;
    return () => {
      finished ??= (async () => {
        const response = page.waitForResponse(value => new URL(value.url()).pathname === `/api/exceptions/${id}/history`);
        release();
        await (await response).finished();
        await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      })();
      return finished;
    };
  }
  let release = await delayOlderPage();
  try {
    await page.evaluate(() => { window.location.hash = 'exception/00000000-0000-0000-0000-000000000066'; });
    const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
    await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-1086');
    const otherResponse = await page.request.get('/api/exceptions/00000000-0000-0000-0000-000000000066');
    expect(otherResponse.status()).toBe(200);
    const other = await otherResponse.json();
    await release();
    await expectHistoryPage(page, 1, other.events, other.exception.version);
    await page.evaluate(record => { window.location.hash = `exception/${record}`; }, id);
    await expect(detail.locator('.detail-heading .reference')).toHaveText('NL-HISTORY-001');
    release = await delayOlderPage();
    await refreshWorkspaceAccess(page, 'reviewer');
    const latestResponse = await page.request.get(`/api/exceptions/${id}`);
    expect(latestResponse.status()).toBe(200);
    const latest = await latestResponse.json();
    await expectHistoryPage(page, 1, latest.events, latest.exception.version);
    await release();
    await expectHistoryPage(page, 1, latest.events, latest.exception.version);
    release = await delayOlderPage();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
    await release();
    await expect(page.getByRole('region', { name: 'Change history', exact: true })).toHaveCount(0);
    await login(page, 'harbor', 'reviewer');
    await openRecord(page, 'HS-2057');
    await expect(detail.locator('.detail-heading .reference')).toHaveText('HS-2057');
    expect(await historyVersions(page)).not.toContain(47);
    await expect(page.locator('.workspace')).not.toContainText('History paging synthetic review');
    assertBrowser();
  } finally {
    await release();
    await page.unrouteAll({ behavior: 'wait' });
  }
});

async function signInHere(page: Page, organization: 'northline' | 'harbor', reviewer = false) {
  await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
  await page.getByLabel('Email address', { exact: true }).fill(reviewer
    ? organization === 'northline' ? 'casey@northline.example' : 'taylor@harbor.example'
    : organization === 'northline' ? 'alex@northline.example' : 'jules@harbor.example');
  await page.getByLabel('Password', { exact: true }).fill(demoPassword!);
  const submit = page.getByRole('button', { name: 'Sign in', exact: true });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.locator('.identity')).toContainText(organization === 'northline' ? 'Northline Logistics' : 'Harbor Supply');
  await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
}

async function switchAccountHere(page: Page, organization: 'northline' | 'harbor', reviewer = false) {
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await signInHere(page, organization, reviewer);
}

async function expectOnlyOrganization(page: Page, organization: 'northline' | 'harbor') {
  await expect(page.locator('.identity')).toContainText(organization === 'northline' ? 'Northline Logistics' : 'Harbor Supply');
  await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
  await expect(page.locator('.exception-row')).not.toHaveCount(0);
  const references = await page.locator('.exception-row .reference').allTextContents();
  expect(references.every(value => value.startsWith(organization === 'northline' ? 'NL-' : 'HS-'))).toBe(true);
  await expect(page.locator('.detail-heading')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
}

async function nextFrames(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  test(`${viewport.name} shared-cookie tabs clear private state and adopt the actual next account`, async ({ page, context }) => {
    loginAdmissionFixture('expire');
    const assertFirst = observeBrowser(page);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await login(page);
    await searchQueue(page, 'NL-HISTORY-001', 1);
    await openRecord(page, 'NL-HISTORY-001');
    await page.getByLabel('Resolution note', { exact: true }).fill('Private draft from the previous account.');
    await page.evaluate(() => {
      const state = window as Window & { sessionDocument?: string; sessionMessages?: unknown[] };
      state.sessionDocument = 'same document'; state.sessionMessages = [];
      const observer = new BroadcastChannel('shipment-workspace-session-v1');
      observer.addEventListener('message', event => state.sessionMessages!.push(event.data));
      window.addEventListener('pagehide', () => observer.close(), { once: true });
    });
    let firstBusinessPosts = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) firstBusinessPosts++;
    });
    const second = await context.newPage();
    const assertSecond = observeBrowser(second);
    try {
      await second.goto('/');
      await expect(second.locator('.identity')).toContainText('Northline Logistics');
      await second.getByRole('button', { name: 'Sign out', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
      await expect(page.locator('.detail-heading')).toHaveCount(0);
      await signInHere(second, 'harbor', true);
      await expectOnlyOrganization(page, 'harbor');
      await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
      expect(await page.evaluate(() => (window as Window & { sessionDocument?: string }).sessionDocument)).toBe('same document');
      await expect(page.getByLabel('Resolution note', { exact: true })).toHaveCount(0);
      const messages = await page.evaluate(() => (window as Window & { sessionMessages?: unknown[] }).sessionMessages);
      expect(messages?.length).toBeGreaterThanOrEqual(2);
      expect(messages?.every(value => JSON.stringify(value) === JSON.stringify({ v: 1, type: 'session-changed' }))).toBe(true);
      expect(firstBusinessPosts).toBe(0);
      await assertNoHorizontalOverflow(page);
      await screenshot(page, `${viewport.name}-session-change.png`);
      assertFirst(); assertSecond();
    } finally { await second.close(); }
  });
}

for (const channelMode of ['missing', 'constructor-throws', 'post-throws'] as const) {
  test(`${channelMode} channel still rejects stale expected context before displaying another account`, async ({ page, context }) => {
    loginAdmissionFixture('expire');
    test.info().annotations.push({ type: 'fixture-only', description: 'Browser channel and lifecycle notifications are disabled in this fixture to exercise the actual server context-mismatch recovery path.' });
    await context.addInitScript(mode => {
      if (mode === 'missing') Object.defineProperty(window, 'BroadcastChannel', { configurable: true, value: undefined });
      else if (mode === 'constructor-throws') Object.defineProperty(window, 'BroadcastChannel', { configurable: true, value: class { constructor() { throw new Error('Synthetic channel failure'); } } });
      else {
        const Native = window.BroadcastChannel;
        Object.defineProperty(window, 'BroadcastChannel', { configurable: true, value: class extends Native {
          postMessage() { throw new Error('Synthetic postMessage failure'); }
        } });
      }
      window.addEventListener('focus', event => event.stopImmediatePropagation(), true);
      document.addEventListener('visibilitychange', event => event.stopImmediatePropagation(), true);
    }, channelMode);
    const assertFirst = observeBrowser(page, { expectedStatus: 409 });
    await login(page);
    const second = await context.newPage();
    const assertSecond = observeBrowser(second);
    try {
      await second.goto('/');
      await expect(second.locator('.identity')).toContainText('Northline Logistics');
      await switchAccountHere(second, 'harbor', true);
      await expect(page.locator('.identity')).toContainText('Northline Logistics');
      const mismatch = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === '/api/exceptions' && response.status() === 409);
      await page.getByLabel('Search references and summaries', { exact: true }).fill('HS-');
      await page.getByRole('button', { name: 'Search queue', exact: true }).click();
      expect((await (await mismatch).json()).error.code).toBe('session_changed');
      await expectOnlyOrganization(page, 'harbor');
      await expect(page.locator('.session-message')).toContainText('account or session changed');
      assertFirst(); assertSecond();
    } finally { await second.close(); }
  });
}

for (const kind of ['queue', 'detail', 'history'] as const) {
  test(`a delayed actual ${kind} response cannot enter a new account on the same document`, async ({ page, context }) => {
    loginAdmissionFixture('expire');
    const assertFirst = observeBrowser(page);
    await login(page, 'northline', 'reviewer');
    await page.evaluate(() => { (window as Window & { sessionDocument?: string }).sessionDocument = 'original delayed-response document'; });
    await searchQueue(page, 'NL-HISTORY-001', 1);
    await openRecord(page, 'NL-HISTORY-001');
    const id = new URL(page.url()).hash.split('/')[1];
    let release!: () => void;
    let arrived!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const received = new Promise<void>(resolve => { arrived = resolve; });
    const pathname = kind === 'queue' ? '/api/exceptions' : kind === 'detail' ? `/api/exceptions/${id}` : `/api/exceptions/${id}/history`;
    const pattern = kind === 'queue' ? '**/api/exceptions?**' : kind === 'detail' ? `**/api/exceptions/${id}` : `**/api/exceptions/${id}/history?**`;
    await page.route(pattern, async route => {
      const actual = await route.fetch();
      expect(actual.status()).toBe(200);
      arrived(); await gate;
      await route.fulfill({ response: actual });
    }, { times: 1 });
    if (kind === 'queue') {
      await page.getByLabel('Search references and summaries', { exact: true }).fill('NL-');
      await page.getByRole('button', { name: 'Search queue', exact: true }).click();
    } else if (kind === 'detail') {
      await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    } else await page.getByRole('button', { name: 'Older changes', exact: true }).click();
    await received;
    const second = await context.newPage();
    const assertSecond = observeBrowser(second);
    try {
      await second.goto('/');
      await expect(second.locator('.identity')).toContainText('Northline Logistics');
      await switchAccountHere(second, 'harbor', true);
      await expectOnlyOrganization(page, 'harbor');
      await openRecord(page, 'HS-2057');
      const delivered = page.waitForResponse(response => new URL(response.url()).pathname === pathname);
      release(); await (await delivered).finished(); await nextFrames(page);
      await expect(page.locator('.identity')).toContainText('Harbor Supply');
      expect(await page.evaluate(() => (window as Window & { sessionDocument?: string }).sessionDocument)).toBe('original delayed-response document');
      await expect(page.locator('.detail-heading .reference')).toHaveText('HS-2057');
      await expect(page.locator('.workspace')).not.toContainText('History paging synthetic review');
      expect((await page.locator('.exception-row .reference').allTextContents()).every(value => value.startsWith('HS-'))).toBe(true);
      const actual = await page.request.get('/api/exceptions/00000000-0000-0000-0000-0000000000c9');
      expect(actual.status()).toBe(200);
      const expected = await actual.json();
      expect(await historyVersions(page)).toEqual(expected.events.map((event: { version: number }) => event.version));
      assertFirst(); assertSecond();
    } finally {
      release(); await page.unrouteAll({ behavior: 'wait' }); await second.close();
    }
  });
}

for (const delivery of ['dropped', 'delayed'] as const) {
  test(`an actually committed ${delivery} mutation is retired across a session change without replay`, async ({ page, context }) => {
    loginAdmissionFixture('expire');
    const assertFirst = observeBrowser(page, { expectedFailedRequest: /\/api\/exceptions\/[^/]+\/assign$/ });
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    const sessionResponse = await page.request.get('/api/session');
    const session = await sessionResponse.json();
    const reference = `NL-SESSION-${delivery.toUpperCase()}`;
    const createdResponse = await page.request.post('/api/exceptions', {
      headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': await page.evaluate(() => crypto.randomUUID()) },
      data: { reference, summary: 'Synthetic session transition', details: 'Disposable interrupted mutation acceptance.', priority: 'normal' },
    });
    expect(createdResponse.status()).toBe(201);
    const created = await createdResponse.json();
    await page.evaluate(id => { window.location.hash = `exception/${id}`; }, created.exception.id);
    await expect(page.locator('.detail-heading .reference')).toHaveText(reference);
    let release!: () => void;
    let arrived!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const committed = new Promise<void>(resolve => { arrived = resolve; });
    let attempts = 0;
    const path = `/api/exceptions/${created.exception.id}/assign`;
    await page.route(`**${path}`, async route => {
      attempts++;
      const actual = await route.fetch();
      expect(actual.status()).toBe(200);
      expect((await actual.json()).exception.version).toBe(2);
      arrived();
      if (delivery === 'dropped') await route.abort('failed');
      else { await gate; await route.fulfill({ response: actual }); }
    });
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await committed;
    if (delivery === 'dropped') await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeVisible();
    const second = await context.newPage();
    const assertSecond = observeBrowser(second);
    try {
      await second.goto('/');
      await expect(second.locator('.identity')).toContainText('Northline Logistics');
      // Re-authenticating the same actor must also retire its earlier intent.
      await switchAccountHere(second, delivery === 'dropped' ? 'northline' : 'harbor');
      await expectOnlyOrganization(page, delivery === 'dropped' ? 'northline' : 'harbor');
      await expect(page.locator('.session-message')).toContainText('An earlier change may already be saved.');
      await expect(page.locator('.session-message')).toContainText('local retry was retired');
      if (delivery === 'delayed') {
        const delivered = page.waitForResponse(response => new URL(response.url()).pathname === path);
        release(); await (await delivered).finished(); await nextFrames(page);
        await expect(page.locator('.identity')).toContainText('Harbor Supply');
        await expect(page.locator('.session-message')).toContainText('An earlier change may already be saved.');
      } else {
        const currentResponse = await page.request.get(`/api/exceptions/${created.exception.id}`);
        expect(currentResponse.status()).toBe(200);
        const current = await currentResponse.json();
        expect(current.exception.version).toBe(2);
        expect(current.events).toHaveLength(2);
        expect(current.events.map((event: { action: string }) => event.action)).toEqual(['created', 'assigned']);
      }
      expect(attempts).toBe(1);
      await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
      await assertNoHorizontalOverflow(page);
      assertFirst(); assertSecond();
    } finally { release(); await page.unrouteAll({ behavior: 'wait' }); await second.close(); }
  });
}

test('session hints are strict, coalesced and authoritative while resumption preserves a matching draft', async ({ page }) => {
  loginAdmissionFixture('expire');
  const assertBrowser = observeBrowser(page);
  await login(page);
  await searchQueue(page, 'NL-HISTORY-001', 1);
  await openRecord(page, 'NL-HISTORY-001');
  const draft = 'Preserve this draft when the actual account is unchanged.';
  await page.getByLabel('Resolution note', { exact: true }).fill(draft);
  for (const event of ['focus', 'visibilitychange', 'pageshow'] as const) {
    const checked = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
    await page.evaluate(kind => {
      if (kind === 'focus') window.dispatchEvent(new Event('focus'));
      else if (kind === 'visibilitychange') document.dispatchEvent(new Event('visibilitychange'));
      else window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    }, event);
    expect((await checked).status()).toBe(200);
    await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
    await expect(page.getByLabel('Resolution note', { exact: true })).toHaveValue(draft);
  }
  let checks = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/session') checks++; });
  await page.evaluate(() => {
    const channel = new BroadcastChannel('shipment-workspace-session-v1');
    for (const value of [null, [], { v: 2, type: 'session-changed' }, { v: 1, type: 'other' }, { v: 1, type: 'session-changed', user: 'untrusted' }]) channel.postMessage(value);
    channel.close();
  });
  await nextFrames(page);
  expect(checks).toBe(0);
  await expect(page.getByLabel('Resolution note', { exact: true })).toHaveValue(draft);
  let release!: () => void;
  let arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const first = new Promise<void>(resolve => { arrived = resolve; });
  let routed = 0;
  await page.route('**/api/session', async route => {
    routed++;
    if (routed === 1) {
      const actual = await route.fetch();
      arrived(); await gate; await route.fulfill({ response: actual });
    } else await route.continue();
  });
  try {
    await page.evaluate(() => {
      const channel = new BroadcastChannel('shipment-workspace-session-v1');
      for (let index = 0; index < 20; index++) channel.postMessage({ v: 1, type: 'session-changed' });
      channel.close();
    });
    await first; await nextFrames(page);
    expect(routed).toBe(1);
    await expect(page.locator('.detail-heading')).toHaveCount(0);
    release();
    await expectOnlyOrganization(page, 'northline');
    expect(routed).toBe(2);
    assertBrowser();
  } finally { release(); await page.unrouteAll({ behavior: 'wait' }); }
});

test('a failed authoritative session check hides private state and has a manual retry without replay', async ({ page }) => {
  loginAdmissionFixture('expire');
  const assertBrowser = observeBrowser(page, { expectedStatus: 503 });
  await login(page);
  await searchQueue(page, 'NL-HISTORY-001', 1);
  await openRecord(page, 'NL-HISTORY-001');
  await page.getByLabel('Resolution note', { exact: true }).fill('Private unsent draft before a failed check.');
  let businessPosts = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
  });
  await page.route('**/api/session', route => route.fulfill({ status: 503, contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'synthetic_unavailable', message: 'Synthetic session failure.' } }) }), { times: 1 });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByRole('button', { name: 'Check current session', exact: true })).toBeEnabled();
  await expect(page.locator('.identity')).toHaveCount(0);
  await expect(page.locator('.workspace')).toHaveCount(0);
  await expect(page.locator('.session-message')).toContainText('current session could not be confirmed');
  await page.getByRole('button', { name: 'Check current session', exact: true }).click();
  await expectOnlyOrganization(page, 'northline');
  await expect(page.locator('.detail-heading')).toHaveCount(0);
  expect(businessPosts).toBe(0);
  assertBrowser();
});

test('incorrect credentials retain the anonymous form without automatic session recovery or retry', async ({ page }) => {
  loginAdmissionFixture('expire');
  const assertBrowser = observeBrowser(page, { expectedStatus: 401 });
  const form = await prepareSignIn(page, 'Synthetic incorrect password');
  await expect(form.submit).toBeEnabled();
  const beforeResponse = await page.request.get('/api/session');
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  expect(before.authenticated).toBe(false);
  let loginPosts = 0;
  let sessionReads = 0;
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/login' && request.method() === 'POST') loginPosts++;
    if (path === '/api/session' && request.method() === 'GET') sessionReads++;
  });
  const rejected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/login');
  await form.submit.click();
  const response = await rejected;
  expect(response.status()).toBe(401);
  expect((await response.json()).error.code).toBe('invalid_credentials');
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect.');
  await expect(form.email).toHaveValue('alex@northline.example');
  await expect(form.password).toHaveValue('Synthetic incorrect password');
  await expect(form.submit).toBeEnabled();
  await expect(page.locator('.session-message')).toHaveCount(0);
  await nextFrames(page);
  expect(loginPosts).toBe(1);
  expect(sessionReads).toBe(0);
  const afterResponse = await page.request.get('/api/session');
  expect(afterResponse.status()).toBe(200);
  const after = await afterResponse.json();
  expect(after.authenticated).toBe(false);
  expect(after.session_context).toBe(before.session_context);
  await form.password.fill(demoPassword!);
  await form.submit.click();
  await expectOnlyOrganization(page, 'northline');
  expect(loginPosts).toBe(2);
  expect(sessionReads).toBe(0);
  assertBrowser();
});
async function createRoleRecoveryRecord(page: Page, suffix: string) {
  const current = await (await page.request.get('/api/session')).json();
  const created = await page.request.post('/api/exceptions', {
    headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': current.csrf_token,
      'X-Workspace-Context': current.session_context, 'Idempotency-Key': crypto.randomUUID() },
    data: { reference: `NL-ROLE-${suffix}`, summary: `Role recovery ${suffix}`,
      details: 'Synthetic record created through the actual API for role recovery acceptance.', priority: 'normal' },
  });
  expect(created.status()).toBe(201);
  const id = (await created.json()).exception.id as string;
  await page.evaluate(value => { window.location.hash = `exception/${value}`; }, id);
  await expect(page.locator('.detail-heading .reference')).toHaveText(`NL-ROLE-${suffix}`);
  return { id, session: current };
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  for (const responseMode of ['dropped', 'held'] as const) {
    test(`${viewport.name} session-observed read-only access retires a ${responseMode} operator change without replay`, async ({ page }) => {
      loginAdmissionFixture('expire');
      roleFixture('promote-alex');
      const assertBrowser = observeBrowser(page, responseMode === 'dropped'
        ? { expectedFailedRequest: /\/api\/exceptions\/[^/]+\/assign$/ } : {});
      let release!: () => void;
      let arrived!: () => void;
      const gate = new Promise<void>(resolve => { release = resolve; });
      const admitted = new Promise<void>(resolve => { arrived = resolve; });
      try {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await login(page);
        const { id, session: beforeSession } = await createRoleRecoveryRecord(page, `${viewport.name}-${responseMode}`);
        await page.evaluate(() => { (window as Window & { recoveryDocument?: string }).recoveryDocument = 'same recovery document'; });
        let businessPosts = 0;
        page.on('request', request => {
          if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
        });
        let committedStatus: number | undefined;
        await page.route(`**/api/exceptions/${id}/assign`, async route => {
          const actual = await route.fetch();
          committedStatus = actual.status();
          arrived();
          if (responseMode === 'dropped') await route.abort('failed');
          else { await gate; await route.fulfill({ response: actual }); }
        });
        await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
        await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
        await admitted;
        expect(committedStatus).toBe(200);
        if (responseMode === 'dropped') {
          await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeEnabled();
        }
        const saved = await (await page.request.get(`/api/exceptions/${id}`)).json();
        expect(saved.exception.version).toBe(2);
        expect(saved.exception.assignee_name).toBe('Sam Rivera');
        expect(saved.events).toHaveLength(2);
        roleFixture('demote-alex');
        const checked = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
        await page.evaluate(() => window.dispatchEvent(new Event('focus')));
        const current = await (await checked).json();
        expect(current.user.id).toBe(beforeSession.user.id);
        expect(current.user.organization_id).toBe(beforeSession.user.organization_id);
        expect(current.session_context).toBe(beforeSession.session_context);
        expect(current.user.role).toBe('reviewer');
        await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
        await expect(page.locator('.session-message')).toContainText('Your current access is read-only.');
        await expect(page.locator('.session-message')).toContainText('An earlier change may already be saved.');
        await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
        await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeEnabled();
        await expect(page.getByRole('button', { name: 'Search queue', exact: true })).toBeEnabled();
        await expect(page.locator('.exception-row')).not.toHaveCount(0);
        await expect(page.locator('.detail-heading')).toHaveCount(0);
        expect(await page.evaluate(() => (window as Window & { recoveryDocument?: string }).recoveryDocument)).toBe('same recovery document');
        if (responseMode === 'held') {
          const delivered = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/assign'));
          release();
          const oldResponse = await delivered;
          expect(oldResponse.status()).toBe(200);
          await oldResponse.finished();
          await nextFrames(page);
          await expect(page.getByText('Assignment saved.', { exact: true })).toHaveCount(0);
          await expect(page.locator('.session-message')).toContainText('An earlier change may already be saved.');
          await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
          await expect(page.locator('.detail-heading')).toHaveCount(0);
        }
        await refreshWorkspaceAccess(page, 'reviewer');
        await searchQueue(page, `NL-ROLE-${viewport.name}-${responseMode}`, 1);
        const detail = await openRecord(page, `NL-ROLE-${viewport.name}-${responseMode}`);
        await expect(detail.locator('.record-meta')).toContainText('Version 2');
        await expect(detail.locator('.history-list li')).toHaveCount(2);
        await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
        expect(await (await page.request.get(`/api/exceptions/${id}`)).json()).toEqual(saved);
        expect(businessPosts).toBe(1);
        await assertNoHorizontalOverflow(page);
        await screenshot(page, `${viewport.name}-role-recovery-${responseMode}.png`);
        await page.getByRole('button', { name: 'Sign out', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Sign in to the workspace', exact: true })).toBeVisible();
        expect(businessPosts).toBe(1);
        assertBrowser();
      } finally {
        release();
        roleFixture('promote-alex');
        await page.unrouteAll({ behavior: 'wait' });
      }
    });
  }
}

test('a matching operator session check preserves the same uncertain retry identity', async ({ page }) => {
  loginAdmissionFixture('expire');
  roleFixture('promote-alex');
  const assertBrowser = observeBrowser(page, { expectedFailedRequest: /\/api\/exceptions\/[^/]+\/assign$/ });
  await login(page);
  const { id, session: beforeSession } = await createRoleRecoveryRecord(page, 'operator-retry');
  const attempts: { key: string | undefined; body: string | null }[] = [];
  await page.route(`**/api/exceptions/${id}/assign`, async route => {
    const request = route.request();
    attempts.push({ key: request.headers()['idempotency-key'], body: request.postData() });
    if (attempts.length === 1) {
      expect((await route.fetch()).status()).toBe(200);
      await route.abort('failed');
    } else await route.continue();
  });
  await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
  await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeEnabled();
  const saved = await (await page.request.get(`/api/exceptions/${id}`)).json();
  const checked = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  const current = await (await checked).json();
  expect(current.session_context).toBe(beforeSession.session_context);
  expect(current.user.role).toBe('operator');
  await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toBeEnabled();
  expect(attempts).toHaveLength(1);
  await page.getByRole('button', { name: 'Retry same change', exact: true }).click();
  await expect(page.getByText('Assignment saved.', { exact: true })).toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  expect(await (await page.request.get(`/api/exceptions/${id}`)).json()).toEqual(saved);
  assertBrowser();
});

async function prepareRefreshRecord(page: Page, suffix: string) {
  loginAdmissionFixture('expire');
  roleFixture('promote-alex');
  await page.goto('/');
  await signInHere(page, 'northline');
  const session = await (await page.request.get('/api/session')).json();
  const reference = `NL-RF-${suffix}`;
  const created = await page.request.post('/api/exceptions', {
    headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': session.csrf_token,
      'X-Workspace-Context': session.session_context, 'Idempotency-Key': crypto.randomUUID() },
    data: { reference, summary: 'Explicit refresh acceptance', details: 'Synthetic refresh coordination record.', priority: 'normal' },
  });
  expect(created.status()).toBe(201);
  const id = (await created.json()).exception.id as string;
  await searchQueue(page, reference, 1);
  const detail = await openRecord(page, reference);
  await expect(detail.locator('.record-meta')).toContainText('Version 1');
  const assigned = await page.request.post(`/api/exceptions/${id}/assign`, {
    headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': session.csrf_token,
      'X-Workspace-Context': session.session_context, 'Idempotency-Key': crypto.randomUUID() },
    data: { expected_version: 1, assignee_id: '00000000-0000-0000-0000-00000000000c' },
  });
  expect(assigned.status()).toBe(200);
  expect((await assigned.json()).exception.version).toBe(2);
  const saved = await (await page.request.get(`/api/exceptions/${id}`)).json();
  expect(saved.exception.version).toBe(2);
  expect(saved.events.map((event: { version: number }) => event.version)).toEqual([1, 2]);
  await page.evaluate(() => { (window as Window & { refreshDocument?: string }).refreshDocument = 'original refresh document'; });
  return { id, reference, session, saved, detail };
}

async function holdRefreshChecks(page: Page, failSecond = false) {
  let releaseFirst!: () => void;
  let releaseSecond!: () => void;
  let firstArrived!: () => void;
  let secondArrived!: () => void;
  const firstGate = new Promise<void>(resolve => { releaseFirst = resolve; });
  const secondGate = new Promise<void>(resolve => { releaseSecond = resolve; });
  const first = new Promise<void>(resolve => { firstArrived = resolve; });
  const second = new Promise<void>(resolve => { secondArrived = resolve; });
  let checks = 0;
  const roles: string[] = [];
  await page.route('**/api/session', async route => {
    const index = ++checks;
    const actual = await route.fetch();
    expect(actual.status()).toBe(200);
    roles.push((await actual.json()).user?.role ?? 'anonymous');
    if (index === 1) { firstArrived(); await firstGate; }
    if (index === 2) { secondArrived(); await secondGate; }
    if (index === 2 && failSecond) {
      // The server answered normally. This declared client-delivery fixture
      // replaces only the trailing response with an unavailable-check error.
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'fixture_unavailable', message: 'Synthetic session check unavailable.' } }) });
    } else await route.fulfill({ response: actual });
  });
  return { first, second, releaseFirst, releaseSecond, roles, count: () => checks,
    async close() { releaseFirst(); releaseSecond(); await page.unrouteAll({ behavior: 'wait' }); } };
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
  test(`${viewport.name} explicit refresh survives a matching focus check`, async ({ page }) => {
    const assertBrowser = observeBrowser(page);
    await page.setViewportSize(viewport);
    const record = await prepareRefreshRecord(page, viewport.name === 'desktop' ? 'D' : 'N');
    if (viewport.name === 'narrow') {
      // CSSOM changes only this isolated page. Verify actual text resizing
      // without weakening the application's self-only style policy.
      const original = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
      await page.evaluate(size => { document.documentElement.style.fontSize = `${size * 2}px`; }, original);
      expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize))).toBe(original * 2);
    }
    const barriers = await holdRefreshChecks(page);
    let businessPosts = 0;
    let dataReads = 0;
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path.startsWith('/api/exceptions')) businessPosts++;
      if (request.method() === 'GET' && path.startsWith('/api/exceptions')) dataReads++;
    });
    try {
      const refresh = page.getByRole('button', { name: 'Refresh workspace', exact: true });
      await refresh.focus();
      await expect(refresh).toBeFocused();
      await page.keyboard.press('Enter');
      await barriers.first;
      // Synchronous dispatch proves the lifecycle listener ran before delivery.
      // It does not simulate physical mobile suspension or browser restoration.
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      barriers.releaseFirst();
      await barriers.second;
      await expect(record.detail.locator('.record-meta')).toContainText('Version 1');
      expect(dataReads).toBe(0);
      const delivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
      barriers.releaseSecond();
      await (await delivered).finished();
      await expect(refresh).toBeEnabled();
      expect(barriers.roles).toEqual(['operator', 'operator']);
      expect(barriers.count()).toBe(2);
      expect(businessPosts).toBe(0);
      await expect(record.detail.locator('.record-meta')).toContainText('Version 2');
      await expect(page.getByText('Showing the first queue page and the latest saved record. Review it before making another change.', { exact: true })).toBeVisible();
      await expect(record.detail.locator('.history-list li')).toHaveCount(2);
      await expect(page.getByLabel('Assigned to', { exact: true })).toHaveValue('00000000-0000-0000-0000-00000000000c');
      expect(await (await page.request.get(`/api/exceptions/${record.id}`)).json()).toEqual(record.saved);
      expect(await page.evaluate(() => (window as Window & { refreshDocument?: string }).refreshDocument)).toBe('original refresh document');
      await assertNoHorizontalOverflow(page);
      await screenshot(page, `${viewport.name}-explicit-refresh.png`);
      assertBrowser();
    } finally { await barriers.close(); }
  });
}

test('read-only denial cleanup joins an active check without retiring readable detail', async ({ page }) => {
  const assertBrowser = observeBrowser(page, { expectedStatus: 403 });
  const record = await prepareRefreshRecord(page, 'J');
  const barriers = await holdRefreshChecks(page);
  let releaseDenial!: () => void;
  let denialArrived!: () => void;
  const denialGate = new Promise<void>(resolve => { releaseDenial = resolve; });
  const denied = new Promise<void>(resolve => { denialArrived = resolve; });
  let businessPosts = 0;
  await page.route(`**/api/exceptions/${record.id}/assign`, async route => {
    businessPosts++;
    const actual = await route.fetch();
    expect(actual.status()).toBe(403);
    expect((await actual.json()).error.code).toBe('read_only');
    denialArrived(); await denialGate;
    await route.fulfill({ response: actual });
  });
  try {
    roleFixture('demote-alex');
    await page.getByLabel('Assigned to', { exact: true }).selectOption({ label: 'Sam Rivera' });
    await page.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await denied;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await barriers.first;
    const denialDelivered = page.waitForResponse(response => new URL(response.url()).pathname === `/api/exceptions/${record.id}/assign`);
    releaseDenial(); await (await denialDelivered).finished();
    await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
    barriers.releaseFirst();
    await barriers.second;
    const delivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
    barriers.releaseSecond();
    await (await delivered).finished();
    await expect(page.getByRole('button', { name: 'Refresh workspace', exact: true })).toBeEnabled();
    await expect(record.detail.locator('.detail-heading .reference')).toHaveText(record.reference);
    await expect(page.getByRole('button', { name: 'Retry same change', exact: true })).toHaveCount(0);
    expect(barriers.roles).toEqual(['reviewer', 'reviewer']);
    expect(businessPosts).toBe(1);
    await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    await expect(record.detail.locator('.record-meta')).toContainText('Version 2');
    expect(await (await page.request.get(`/api/exceptions/${record.id}`)).json()).toEqual(record.saved);
    expect(businessPosts).toBe(1);
    assertBrowser();
  } finally { releaseDenial(); await barriers.close(); roleFixture('promote-alex'); }
});

test('explicit refresh uses trailing current reviewer access without a business replay', async ({ page }) => {
  const assertBrowser = observeBrowser(page);
  const record = await prepareRefreshRecord(page, 'R');
  const barriers = await holdRefreshChecks(page);
  let businessPosts = 0;
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++; });
  try {
    await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    await barriers.first;
    roleFixture('demote-alex');
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    barriers.releaseFirst();
    await barriers.second;
    const delivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
    barriers.releaseSecond();
    await (await delivered).finished();
    await expect(page.locator('.identity .access-role')).toHaveText('Read-only reviewer');
    await expect(record.detail.locator('.record-meta')).toContainText('Version 2');
    await expect(page.getByRole('button', { name: 'New exception', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Resolution note', { exact: true })).toHaveCount(0);
    expect(barriers.roles).toEqual(['operator', 'reviewer']);
    expect(businessPosts).toBe(0);
    expect(await (await page.request.get(`/api/exceptions/${record.id}`)).json()).toEqual(record.saved);
    assertBrowser();
  } finally { await barriers.close(); roleFixture('promote-alex'); }
});

test('explicit refresh fails closed on a trailing check error and recovers manually', async ({ page }) => {
  const assertBrowser = observeBrowser(page, { expectedStatus: 503 });
  const record = await prepareRefreshRecord(page, 'F');
  const barriers = await holdRefreshChecks(page, true);
  let businessPosts = 0;
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++; });
  try {
    await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    await barriers.first;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    barriers.releaseFirst();
    await barriers.second;
    const delivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session' && response.status() === 503);
    barriers.releaseSecond();
    await (await delivered).finished();
    await expect(page.locator('.detail-heading')).toHaveCount(0);
    await expect(page.locator('.session-message')).toContainText('could not be confirmed');
    await expect(page.getByText('Showing the first queue page and the latest saved record. Review it before making another change.', { exact: true })).toHaveCount(0);
    const recover = page.getByRole('button', { name: 'Check current session', exact: true });
    await recover.focus();
    await expect(recover).toBeFocused();
    await page.keyboard.press('Enter');
    await expectOnlyOrganization(page, 'northline');
    await searchQueue(page, record.reference, 1);
    await openRecord(page, record.reference);
    await expect(record.detail.locator('.record-meta')).toContainText('Version 2');
    expect(businessPosts).toBe(0);
    expect(await (await page.request.get(`/api/exceptions/${record.id}`)).json()).toEqual(record.saved);
    assertBrowser();
  } finally { await barriers.close(); }
});

test('an account change retires a held explicit refresh without entering the next workspace', async ({ page, context }) => {
  const assertBrowser = observeBrowser(page);
  const record = await prepareRefreshRecord(page, 'A');
  const barriers = await holdRefreshChecks(page);
  const second = await context.newPage();
  const assertSecond = observeBrowser(second);
  let businessPosts = 0;
  let retiredDetailReads = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/exceptions')) businessPosts++;
    if (request.method() === 'GET' && new URL(request.url()).pathname === `/api/exceptions/${record.id}`) retiredDetailReads++;
  });
  try {
    await page.getByRole('button', { name: 'Refresh workspace', exact: true }).click();
    await barriers.first;
    await second.goto('/');
    await switchAccountHere(second, 'harbor', true);
    await expect(page.locator('.detail-heading')).toHaveCount(0);
    const delivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/session');
    barriers.releaseFirst();
    await (await delivered).finished();
    await barriers.second;
    barriers.releaseSecond();
    await expectOnlyOrganization(page, 'harbor');
    expect(await page.evaluate(() => (window as Window & { refreshDocument?: string }).refreshDocument)).toBe('original refresh document');
    await expect(page.locator('.workspace')).not.toContainText(record.reference);
    expect(retiredDetailReads).toBe(0);
    expect(businessPosts).toBe(0);
    assertBrowser(); assertSecond();
  } finally { await barriers.close(); await second.close(); }
});
