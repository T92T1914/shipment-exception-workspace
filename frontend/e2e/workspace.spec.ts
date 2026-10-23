import { expect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

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

async function login(page: Page, organization: 'northline' | 'harbor' = 'northline') {
  await page.goto('/');
  const email = page.getByLabel('Email address');
  await expect(email).toBeVisible();
  await email.focus();
  await expect(email).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
  await email.fill(organization === 'northline' ? 'alex@northline.example' : 'jules@harbor.example');
  await page.getByLabel('Password', { exact: true }).fill(demoPassword!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Shipment exceptions', exact: true })).toBeVisible();
  await expect(page.locator('.identity')).toContainText(organization === 'northline' ? 'Northline Logistics' : 'Harbor Supply');
  await expect(page.locator('.exception-row')).toHaveCount(organization === 'northline' ? 3 : 2);
}

async function openRecord(page: Page, reference: string) {
  await page.getByRole('button', { name: new RegExp(reference) }).click();
  const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
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
  await expect(page.getByRole('status')).toContainText('Showing the latest saved record');
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

  await page.route('**/api/exceptions', async route => {
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
    await expect(page.locator('.workspace-messages').getByRole('status')).toContainText('Showing the latest saved record');
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
