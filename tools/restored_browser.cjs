// Two bounded installed-UI readbacks. This does not initialize a restored DB.
const fs = require('node:fs');
const path = require('node:path');
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const statePath = process.env.WORKSPACE_RESTORED_STATE;
if (!statePath) throw Error('Choose the private restored consumer-state.json explicitly.');
const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const output = process.env.WORKSPACE_RESTORED_SCREENSHOTS;
if (!output || !process.env.WORKSPACE_BROWSER_EXECUTABLE) throw Error('Choose owned output and the existing headless executable.');

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.WORKSPACE_BROWSER_EXECUTABLE,
    args: ['--disable-gpu', '--renderer-process-limit=2', '--disable-background-networking'] });
  const results = [];
  try {
    fs.mkdirSync(output, { recursive: false });
    for (const sample of [{ name: 'desktop', width: 1440, height: 1000, email: 'alex@northline.example', role: 'Operator' },
                          { name: 'narrow', width: 390, height: 844, email: 'casey@northline.example', role: 'Read-only reviewer' }]) {
      const context = await browser.newContext({ viewport: { width: sample.width, height: sample.height } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('request', request => {
        const url = new URL(request.url());
        if (['http:', 'https:'].includes(url.protocol) && url.origin !== state.base_url) errors.push('Unexpected external request');
      });
      await page.goto(state.base_url);
      await page.getByLabel('Email address').fill(sample.email);
      await page.getByLabel('Password', { exact: true }).fill(state.demo_password);
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await expect(page.locator('.identity .access-role')).toHaveText(sample.role);
      await page.getByRole('button', { name: /NL-RESTORE-001/ }).click();
      await expect(page.locator('.detail-heading .reference')).toHaveText('NL-RESTORE-001');
      await expect(page.locator('.record-meta')).toContainText('Version 3');
      await expect(page.locator('.history-list li')).toHaveCount(3);
      await expect(page.locator('.resolution-text')).toHaveText('Synthetic receiving handoff confirmed.');
      if (sample.role === 'Read-only reviewer') await expect(page.getByLabel('Assigned to', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: /HS-/ })).toHaveCount(0);
      const size = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
      expect(size.content).toBeLessThanOrEqual(size.viewport);
      expect(errors).toEqual([]);
      await page.screenshot({ path: path.join(output, sample.name + '-restored.png'), fullPage: true, animations: 'disabled' });
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await expect(page.getByLabel('Email address')).toBeVisible();
      results.push({ scenario: sample.name, passed: true, role: sample.role, preserved_history_events: 3 });
      await context.close();
    }
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ passed: true, journeys: results }, null, 2));
    console.log('Two restored installed UI journeys passed at desktop/narrow widths.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
