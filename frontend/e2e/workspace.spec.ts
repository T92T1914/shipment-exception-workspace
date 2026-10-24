import { expect, test, type Page } from '@playwright/test';
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
  const seededReferences = organization === 'northline' ? ['NL-1042', 'NL-1086', 'NL-1091'] : ['HS-2057', 'HS-2073'];
  for (const reference of seededReferences) {
    await expect(page.getByRole('button', { name: new RegExp(reference) })).toBeVisible();
  }
  const references = await page.locator('.exception-row .reference').allTextContents();
  expect(references.length).toBeGreaterThanOrEqual(seededReferences.length);
  expect(references.every(reference => reference.startsWith(organization === 'northline' ? 'NL-' : 'HS-'))).toBe(true);
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

async function fillIntake(page: Page, reference: string, summary: string, details: string, priority: 'normal' | 'high' = 'normal') {
  await page.getByRole('button', { name: 'New exception', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'New shipment exception', exact: true })).toBeVisible();
  await page.getByLabel('Shipment reference', { exact: true }).fill(reference);
  await page.getByLabel('Summary', { exact: true }).fill(summary);
  await page.getByLabel('Exception details', { exact: true }).fill(details);
  await page.getByLabel('Priority', { exact: true }).selectOption(priority);
}

async function expectCreatedRecord(page: Page, reference: string) {
  const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
  await expect(detail.locator('.detail-heading .reference')).toHaveText(reference);
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
  await page.route('**/api/exceptions', async route => {
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
