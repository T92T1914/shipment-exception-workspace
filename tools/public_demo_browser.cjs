'use strict';

// Opt-in journeys for an already running, owner-authorized synthetic demo.
// No application service, provider resource or account is created by this helper.
// Supply one private JSON config with exactly these six fields:
// base_url: owned HTTPS 127.0.0.1 staging origin with an explicit port, or the
//   owned service's HTTPS <service>.onrender.com origin on the default TLS port.
// output: new absolute evidence directory. browser_executable: existing absolute
//   headless Chromium path. playwright_module: existing absolute module path.
// source_revision: complete lowercase Git commit ID. package_version: installed
//   numeric release version. Session.demo supplies the public reviewer credential
//   at runtime. Credentials, cookies and complete session payloads are not saved.
// Local self-signed TLS is an explicit loopback-only exception. Provider TLS uses
// normal certificate verification. Keep results and unreviewed captures private.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

async function run() {
  assert.equal(process.argv.length, 3, 'Pass only the private JSON configuration path.');
  const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const keys = ['base_url', 'output', 'browser_executable', 'playwright_module', 'source_revision', 'package_version'];
  assert.ok(config && typeof config === 'object' && !Array.isArray(config)
    && Object.keys(config).length === keys.length && keys.every(key => Object.hasOwn(config, key)),
  'Use exactly the declared noncredential configuration fields.');
  assert.ok(typeof config.base_url === 'string' && !/[^\x21-\x7e]/.test(config.base_url),
    'Supply the owned ASCII HTTPS origin without whitespace or control characters.');
  const base = new URL(config.base_url);
  const localStaging = /^https:\/\/127\.0\.0\.1:[0-9]{4,5}\/?$/.test(config.base_url)
    && Number(base.port) >= 1024 && Number(base.port) <= 65535;
  const publicProvider = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.onrender\.com(?::443)?\/?$/.test(config.base_url)
    && base.port === '';
  assert.ok(base.protocol === 'https:' && !base.username && !base.password
    && base.pathname === '/' && !base.search && !base.hash && (localStaging || publicProvider),
  'Use only an owned HTTPS loopback staging origin or an owned onrender.com service on the default TLS port.');
  const allowLocalSelfSigned = localStaging;
  const evidenceClass = localStaging ? 'loopback-staging' : 'public-provider-journey';
  assert.ok(!publicProvider || process.env.NODE_TLS_REJECT_UNAUTHORIZED !== '0',
    'Provider journeys require normal TLS verification in the process environment.');
  assert.match(config.source_revision, /^[0-9a-f]{40}$/, 'Supply the complete source revision label.');
  assert.match(config.package_version, /^\d+\.\d+\.\d+$/, 'Supply the installed release version label.');
  for (const key of ['output', 'browser_executable', 'playwright_module']) {
    assert.ok(typeof config[key] === 'string' && path.isAbsolute(config[key]),
      'Use explicit absolute owned paths.');
  }
  assert.ok(fs.statSync(config.browser_executable).isFile(), 'Use the existing headless executable.');
  assert.ok(!fs.existsSync(config.output), 'Preserve earlier evidence and choose a new output directory.');
  fs.mkdirSync(config.output);

  // Use the existing caller-selected Playwright installation.
  const { chromium } = require(config.playwright_module);
  const origin = base.origin;
  const scenarios = [
    { name: 'desktop-light-100', width: 1440, height: 1000, theme: 'light', scale: 1, capture: 'resolved' },
    { name: 'desktop-dark-200', width: 1440, height: 1000, theme: 'dark', scale: 2, capture: 'resolved' },
    { name: 'narrow-light-200', width: 390, height: 844, theme: 'light', scale: 2, capture: 'assigned' },
    { name: 'narrow-dark-100', width: 390, height: 844, theme: 'dark', scale: 1, capture: 'resolved' },
  ];
  const journeys = [];
  const unexpected = [];
  const privateValues = new Set();
  const contexts = [];
  const captures = [];
  const themeColors = {};
  let browser;
  let timer;
  let phase = 'launch';
  let current;
  let versionReadback;
  let browserClosed = false;
  let result;

  function safeMessage(error) {
    let message = String(error && error.message || error);
    for (const value of privateValues) if (value) message = message.split(value).join('[withheld]');
    return message.slice(0, 1200);
  }

  async function eventually(check, description) {
    const deadline = Date.now() + 20000;
    while (true) {
      try { await check(); return; }
      catch (error) {
        if (Date.now() >= deadline) throw new Error('Timed out waiting for ' + description + ': ' + safeMessage(error));
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }

  // This delay paces the shared request budget. It is not a latency measurement.
  const pace = () => new Promise(resolve => setTimeout(resolve, 1000));

  function observe(page, journey) {
    page.on('pageerror', error => unexpected.push({ journey: journey.name, kind: 'page-error', name: error.name }));
    page.on('console', message => {
      if (message.type() === 'error') unexpected.push({ journey: journey.name, kind: 'console-error' });
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (request.method() === 'POST' && url.pathname.startsWith('/api/exceptions')) journey.business_posts++;
    });
    page.on('response', response => {
      if (response.status() >= 400) unexpected.push({ journey: journey.name, kind: 'http-error',
        status: response.status(), path: new URL(response.url()).pathname });
    });
    page.on('requestfailed', request => {
      // React aborts superseded GET reads on navigation. No POST failure is excluded.
      if (request.method() === 'GET' && request.failure()?.errorText === 'net::ERR_ABORTED') {
        journey.aborted_get_reads++;
      } else unexpected.push({ journey: journey.name, kind: 'failed-request', path: new URL(request.url()).pathname });
    });
    page.on('popup', popup => { unexpected.push({ journey: journey.name, kind: 'popup' }); void popup.close().catch(() => {}); });
    page.on('download', download => { unexpected.push({ journey: journey.name, kind: 'download' }); void download.cancel().catch(() => {}); });
    page.on('dialog', dialog => { unexpected.push({ journey: journey.name, kind: 'dialog' }); void dialog.dismiss().catch(() => {}); });
  }

  async function focus(page, locator, description) {
    await eventually(async () => assert.ok(await locator.isEnabled()), description + ' to become enabled');
    await locator.scrollIntoViewIfNeeded();
    await locator.focus();
    const observed = await locator.evaluate(element => ({
      focused: document.activeElement === element,
      focus_visible: element.matches(':focus-visible'),
      outline_width: parseFloat(getComputedStyle(element).outlineWidth),
      outline_style: getComputedStyle(element).outlineStyle,
    }));
    assert.ok(observed.focused, description + ' must own keyboard focus.');
    assert.ok(observed.focus_visible && observed.outline_width > 0 && observed.outline_style !== 'none',
      description + ' must retain its visible keyboard focus indicator.');
    current.keyboard.push({ control: description, ...observed });
  }

  async function activate(page, locator, description) {
    // Establish keyboard modality before checking the target's focus treatment.
    await page.keyboard.press('Tab');
    await focus(page, locator, description);
    await page.keyboard.press('Enter');
  }

  async function layout(page, scenario, panel) {
    if (scenario.scale === 2) {
      // CSSOM affects only this isolated document and preserves the application CSP.
      await page.evaluate(size => { document.documentElement.style.fontSize = `${size}px`; }, current.baseline_root_px * 2);
    }
    const dimensions = await page.evaluate(() => ({
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      content_width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      computed_root_px: parseFloat(getComputedStyle(document.documentElement).fontSize),
      dark_media: matchMedia('(prefers-color-scheme: dark)').matches,
      root_background: getComputedStyle(document.documentElement).backgroundColor,
      root_text_color: getComputedStyle(document.documentElement).color,
    }));
    assert.equal(dimensions.viewport_width, scenario.width, 'Use the declared CSS viewport.');
    assert.equal(dimensions.viewport_height, scenario.height, 'Use the declared CSS viewport height.');
    assert.equal(dimensions.computed_root_px, current.baseline_root_px * scenario.scale,
      'The computed root text size must equal the declared scale.');
    assert.equal(dimensions.dark_media, scenario.theme === 'dark', 'Use the declared appearance.');
    const rgbSum = color => {
      const channels = /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)$/.exec(color);
      assert.ok(channels, 'Read the actual computed RGB color.');
      return channels.slice(1).reduce((total, channel) => total + Number(channel), 0);
    };
    assert.ok(scenario.theme === 'dark' ? rgbSum(dimensions.root_background) < 300 : rgbSum(dimensions.root_background) > 600,
      'The actual root background must use the declared light or dark palette.');
    assert.ok(scenario.theme === 'dark' ? rgbSum(dimensions.root_text_color) > 600 : rgbSum(dimensions.root_text_color) < 300,
      'The actual root text must use the declared light or dark palette.');
    assert.ok(dimensions.content_width <= dimensions.viewport_width, 'The actual page must fit without horizontal scrolling.');
    current.dimensions.push({ panel, ...dimensions });
    themeColors[scenario.theme] = dimensions.root_background;
  }

  async function readOnlyControls(page) {
    assert.equal(await page.locator('.identity .access-role').innerText(), 'Read-only reviewer');
    await page.getByRole('region', { name: 'Read-only access', exact: true }).waitFor({ state: 'visible' });
    assert.ok((await page.locator('.access-notice').innerText()).includes('denies business changes on the server'));
    for (const name of ['New exception', 'Create exception', 'Save assignment', 'Confirm resolution', 'Retry same change']) {
      assert.equal(await page.getByRole('button', { name, exact: true }).count(), 0,
        'Public reviewer must have no business mutation controls.');
    }
    assert.equal(await page.getByLabel('Assigned to', { exact: true }).count(), 0);
    assert.equal(await page.getByLabel('Resolution note', { exact: true }).count(), 0);
  }

  async function queueRead(page, action, expected) {
    const response = page.waitForResponse(value => {
      const url = new URL(value.url());
      return value.request().method() === 'GET' && url.pathname === '/api/exceptions'
        && Object.entries(expected).every(([key, value]) => (url.searchParams.get(key) || '') === value);
    });
    await action();
    assert.equal((await response).status(), 200, 'The real queue request must succeed.');
    await pace();
  }

  async function openRecord(page, reference, version, historyActions) {
    await activate(page, page.getByRole('button', { name: new RegExp(reference) }), 'Open ' + reference);
    const detail = page.getByRole('region', { name: 'Exception detail', exact: true });
    await eventually(async () => {
      assert.equal(await detail.locator('.detail-heading .reference').innerText(), reference);
      assert.ok((await detail.locator('.record-meta').innerText()).includes('Version ' + version));
      assert.equal(await detail.locator('.history-list li').count(), historyActions.length);
    }, reference + ' and its complete history');
    const events = await detail.locator('.history-list li').allTextContents();
    for (let index = 0; index < historyActions.length; index++) {
      assert.ok(events[index].includes(historyActions[index]), 'History must preserve the expected action order.');
      assert.ok(events[index].includes('Version ' + (index + 1)), 'History must show consecutive fixture versions.');
    }
    assert.ok((await detail.locator('.action-card').first().innerText()).includes('Sam Rivera'));
    await readOnlyControls(page);
    await pace();
    return detail;
  }

  async function capture(page, filename) {
    await page.screenshot({ path: path.join(config.output, filename), fullPage: true, animations: 'disabled' });
    captures.push(filename);
    current.screenshots.push(filename);
  }

  try {
    browser = await chromium.launch({ executablePath: config.browser_executable, headless: true, timeout: 30000,
      args: ['--disable-gpu', '--renderer-process-limit=2', '--disable-background-networking',
        '--disable-component-update', '--disable-default-apps', '--disable-sync', '--disable-extensions',
        '--no-first-run', '--no-default-browser-check', '--mute-audio', '--autoplay-policy=document-user-activation-required'] });
    timer = setTimeout(() => { unexpected.push({ kind: 'overall-deadline' }); void browser.close().catch(() => {}); }, 240000);
    for (const scenario of scenarios) {
      phase = scenario.name + ':bootstrap';
      current = { name: scenario.name, status: 'running', viewport: { width: scenario.width, height: scenario.height },
        appearance: scenario.theme, text_scale: scenario.scale, business_posts: 0, aborted_get_reads: 0,
        keyboard: [], dimensions: [], screenshots: [], checks: [] };
      journeys.push(current);
      const context = await browser.newContext({ baseURL: origin, viewport: current.viewport,
        colorScheme: scenario.theme, reducedMotion: 'reduce', locale: 'en-US', timezoneId: 'UTC',
        // Provider certificates must verify normally. Only explicit loopback staging is exempt.
        ignoreHTTPSErrors: allowLocalSelfSigned, acceptDownloads: false, permissions: [], serviceWorkers: 'block' });
      contexts.push(context);
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== origin || url.protocol !== 'https:' || request.resourceType() === 'media') {
          unexpected.push({ journey: scenario.name, kind: 'blocked-external-or-media-request' });
          return route.abort('blockedbyclient');
        }
        return route.continue();
      });
      await context.routeWebSocket('**/*', async socket => {
        unexpected.push({ journey: scenario.name, kind: 'blocked-websocket' });
        await socket.close({ code: 1008, reason: 'WebSockets are outside this acceptance route' });
      });
      const page = await context.newPage();
      page.setDefaultTimeout(20000);
      page.setDefaultNavigationTimeout(20000);
      observe(page, current);
      await page.goto(origin + '/', { waitUntil: 'networkidle' });
      const enter = page.getByRole('button', { name: 'Enter synthetic demo', exact: true });
      await enter.waitFor({ state: 'visible' });
      await pace();
      const sessionResponse = await context.request.get('/api/session', { maxRedirects: 0 });
      assert.equal(sessionResponse.status(), 200, 'Read the actual public session descriptor.');
      const session = await sessionResponse.json();
      privateValues.add(session.csrf_token);
      privateValues.add(session.session_context);
      privateValues.add(session.demo?.password);
      assert.ok(!session.authenticated && session.demo?.read_only === true
        && session.demo.email === 'visitor@northline.example' && typeof session.demo.password === 'string'
        && session.demo.password.length >= 12, 'Use the actual separate public reviewer descriptor.');
      const email = page.getByLabel('Email address', { exact: true });
      const password = page.getByLabel('Password', { exact: true });
      assert.ok(await email.evaluate(element => element.readOnly), 'Public email must be read-only.');
      assert.ok(await password.evaluate(element => element.readOnly), 'Public password must be read-only.');
      assert.ok((await email.inputValue()) === session.demo.email && (await password.inputValue()) === session.demo.password,
        'Readonly inputs must use the real public session descriptor.');
      const loginCopy = await page.locator('body').innerText();
      assert.ok(!/Operators:|alex@northline\.example|jules@harbor\.example|local seed setup/.test(loginCopy),
        'Public bootstrap must not advertise stock operator accounts.');
      current.baseline_root_px = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
      assert.ok(current.baseline_root_px > 0, 'Read the actual root text size.');
      await layout(page, scenario, 'login');
      await email.focus();
      await page.keyboard.press('Tab');
      assert.ok(await password.evaluate(element => element === document.activeElement), 'Tab must advance from public email to password.');
      await page.keyboard.press('Tab');
      assert.ok(await enter.evaluate(element => element === document.activeElement), 'Tab must reach the demo entry button.');
      await focus(page, enter, 'Enter synthetic demo');
      await page.keyboard.press('Enter');
      await page.getByRole('heading', { name: 'Shipment exceptions', exact: true }).waitFor({ state: 'visible' });
      await eventually(async () => assert.equal(await page.locator('.exception-row').count(), 3), 'all three Northline records');
      await readOnlyControls(page);
      await layout(page, scenario, 'queue');
      current.checks.push('real-public-descriptor-readonly-inputs', 'keyboard-entry', 'reviewer-only-controls');
      if (!versionReadback) {
        const response = await context.request.get('/api/version', { maxRedirects: 0 });
        assert.equal(response.status(), 200);
        const identity = await response.json();
        assert.ok(identity.version === config.package_version && identity.revision === config.source_revision
          && identity.public_demo === true, 'Actual served identity must match the declared installed candidate.');
        versionReadback = { version: identity.version, revision: identity.revision, public_demo: true };
      }
      await pace();

      phase = scenario.name + ':resolved-search';
      const filter = page.getByLabel('Show exceptions', { exact: true });
      await queueRead(page, () => filter.selectOption('resolved'), { status: 'resolved', q: '' });
      await eventually(async () => {
        assert.equal(await page.locator('.exception-row').count(), 1);
        assert.equal(await page.locator('.exception-row .reference').innerText(), 'NL-1086');
      }, 'resolved filter');
      const search = page.getByLabel('Search references and summaries', { exact: true });
      await search.fill('1086');
      await focus(page, search, 'Search references and summaries');
      await queueRead(page, () => page.keyboard.press('Enter'), { status: 'resolved', q: '1086' });
      assert.ok((await page.locator('.queue-query').innerText()).includes('1086'));
      await openRecord(page, 'NL-1086', 3, ['created the exception', 'assigned Sam Rivera', 'resolved the exception']);
      assert.ok((await page.locator('.resolution-text').innerText()).startsWith('Provisioned synthetic fixture:'));
      await layout(page, scenario, 'resolved-history');
      const resolvedHash = new URL(page.url()).hash;
      assert.equal(resolvedHash, '#exception/00000000-0000-0000-0000-000000000066');
      current.checks.push('real-server-search-and-resolved-filter', 'resolved-v3-three-ordered-events');
      if (scenario.capture === 'resolved') await capture(page, scenario.name + '-resolved-history.png');

      phase = scenario.name + ':reload-and-back';
      await page.reload({ waitUntil: 'networkidle' });
      await eventually(async () => {
        assert.equal(await page.locator('.detail-heading .reference').innerText(), 'NL-1086');
        assert.equal(await page.locator('.history-list li').count(), 3);
      }, 'resolved hash reload');
      assert.equal(new URL(page.url()).hash, resolvedHash);
      await readOnlyControls(page);
      await layout(page, scenario, 'reloaded-detail');
      await pace();
      await page.goBack({ waitUntil: 'domcontentloaded' });
      await eventually(async () => assert.equal(new URL(page.url()).hash, ''), 'browser Back to the queue hash');
      await page.getByRole('heading', { name: 'Your organization', exact: true }).waitFor({ state: 'visible' });
      await layout(page, scenario, 'back-to-queue');
      await pace();
      current.checks.push('authenticated-hash-reload', 'browser-back-navigation');

      phase = scenario.name + ':open-assigned';
      const clear = page.getByRole('button', { name: 'Clear search', exact: true });
      if (await clear.isEnabled()) await queueRead(page, () => clear.click(), { q: '' });
      if (await filter.inputValue() !== 'open') await queueRead(page, () => filter.selectOption('open'), { status: 'open', q: '' });
      await eventually(async () => {
        const references = await page.locator('.exception-row .reference').allTextContents();
        assert.ok(references.includes('NL-1091') && !references.includes('NL-1086'));
        assert.ok(references.every(value => value.startsWith('NL-')));
      }, 'open filter and organization queue');
      await openRecord(page, 'NL-1091', 2, ['created the exception', 'assigned Sam Rivera']);
      assert.equal(await page.locator('.detail-heading .status').innerText(), 'Open');
      await layout(page, scenario, 'open-assigned-history');
      if (scenario.capture === 'assigned') await capture(page, scenario.name + '-assigned-history.png');
      current.checks.push('open-filter-excludes-resolved', 'assigned-open-v2-history', 'synthetic-organization-queue');

      phase = scenario.name + ':sign-out';
      await pace();
      await activate(page, page.getByRole('button', { name: 'Sign out', exact: true }), 'Sign out');
      await page.getByRole('button', { name: 'Enter synthetic demo', exact: true }).waitFor({ state: 'visible' });
      assert.equal(await page.getByRole('heading', { name: 'Shipment exceptions', exact: true }).count(), 0);
      assert.equal(await page.getByRole('button', { name: 'New exception', exact: true }).count(), 0);
      await layout(page, scenario, 'signed-out');
      assert.equal(current.business_posts, 0, 'The real UI must send no business POST.');
      assert.equal(unexpected.length, 0, 'No unexpected page, console, HTTP, network or escape-path event is allowed.');
      current.checks.push('keyboard-sign-out-clears-private-view', 'zero-ui-business-posts');
      current.status = 'passed';
      await context.close();
      await pace();
    }
    assert.notEqual(themeColors.light, themeColors.dark, 'The actual stylesheet must change the root appearance.');
    assert.equal(captures.length, 4, 'Retain one actual application screenshot per journey.');
    result = { status: 'passed' };
  } catch (error) {
    if (current && current.status === 'running') current.status = 'failed';
    result = { status: 'failed', failed_phase: phase, error: safeMessage(error) };
    process.exitCode = 1;
  } finally {
    clearTimeout(timer);
    for (const context of contexts) {
      try { await context.close(); }
      catch { unexpected.push({ kind: 'context-cleanup-failure' }); }
    }
    if (browser) {
      try { await browser.close(); browserClosed = true; }
      catch { unexpected.push({ kind: 'browser-cleanup-failure' }); }
    }
    if (unexpected.length && result?.status === 'passed') { result.status = 'failed'; process.exitCode = 1; }
    result = { ...result, source_revision: config.source_revision, package_version: config.package_version,
      identity_labels: 'Caller labels checked against /api/version. Installed artifact and provider deployment provenance remain separate.',
      evidence_class: evidenceClass, deployment_origin: origin,
      scope: localStaging
        ? 'Isolated loopback HTTPS staging. Public hosting, physical devices, API-negative controls and operator walkthrough remain separate.'
        : 'Actual public-provider browser journeys. Provider ownership, installed artifact provenance, API-negative controls, persistence and physical devices require separate evidence.',
      mode: 'SHARED_PC', self_signed_local_certificate_exception: allowLocalSelfSigned,
      headless: true, sequential_journeys: journeys, served_identity: versionReadback,
      api_business_post_count: journeys.reduce((total, journey) => total + journey.business_posts, 0),
      screenshots: captures, unexpected, browser_close_returned: browserClosed,
      pacing: 'One second between meaningful panels for request-budget pacing, not a performance result.' };
    fs.writeFileSync(path.join(config.output, 'result.json'), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
    process.stdout.write(JSON.stringify({ status: result.status, completed_journeys: journeys.filter(value => value.status === 'passed').length,
      screenshots: captures.length, result: 'result.json' }) + '\n');
  }
}

run().catch(() => {
  process.stderr.write('Public demo browser acceptance could not complete its configuration or result setup.\n');
  process.exitCode = 1;
});
