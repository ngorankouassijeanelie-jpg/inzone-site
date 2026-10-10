const { test, expect } = require('@playwright/test');

// Covers the fail-open regression fixed in this repo: a login error that
// isn't a bad-credentials error (API unreachable, 500, etc.) must never
// grant access to the dashboard. Each page's own login form must fail
// closed, and a legitimate login must still work end to end.

test.describe('admin login (inzone-admin.html)', () => {
  test('wrong password is rejected, dashboard stays locked', async ({ page }) => {
    await page.goto('/inzone-admin.html');
    await page.fill('input[type=password]', 'WRONG_PASSWORD');
    await page.click('button:has-text("Se connecter")');
    await expect(page.locator('#lf')).toBeVisible();
    await expect(page.locator('#l-msg')).toContainText('Identifiants incorrects');
  });

  test('API unreachable is rejected, dashboard stays locked (fail-closed)', async ({ page }) => {
    await page.route('**/api/login', (route) => route.abort('failed'));
    await page.goto('/inzone-admin.html');
    await page.fill('input[type=password]', 'anything');
    await page.click('button:has-text("Se connecter")');
    await expect(page.locator('#lf')).toBeVisible();
    await expect(page.locator('#app')).toBeHidden();
    await expect(page.locator('#l-msg')).toContainText('Connexion impossible');
  });

  test('correct credentials reach the dashboard', async ({ page }) => {
    await page.goto('/inzone-admin.html');
    await page.fill('input[type=password]', 'demonstration');
    await page.click('button:has-text("Se connecter")');
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('#login')).toBeHidden();
  });
});

test.describe('client login (inzone-espace-client.html)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('inz-onb-seen', '1'); } catch (_) {}
    });
  });

  test('wrong password is rejected', async ({ page }) => {
    await page.goto('/inzone-espace-client.html');
    await page.fill('#l-mail', 'investisseur@exemple.ma');
    await page.fill('#l-pass', 'WRONG_PASSWORD');
    await page.click('#lf button[type=submit]');
    await expect(page.locator('#lf')).toBeVisible();
    await expect(page.locator('#l-msg')).toContainText('Identifiants incorrects');
  });

  test('API unreachable is rejected (fail-closed)', async ({ page }) => {
    await page.route('**/api/login', (route) => route.abort('failed'));
    await page.goto('/inzone-espace-client.html');
    await page.fill('#l-mail', 'investisseur@exemple.ma');
    await page.fill('#l-pass', 'demonstration');
    await page.click('#lf button[type=submit]');
    await expect(page.locator('#app')).toBeHidden();
    await expect(page.locator('#l-msg')).toContainText('Connexion impossible');
  });

  test('correct credentials reach the dashboard and show the avatar', async ({ page }) => {
    await page.goto('/inzone-espace-client.html');
    await page.fill('#l-mail', 'investisseur@exemple.ma');
    await page.fill('#l-pass', 'demonstration');
    await page.click('#lf button[type=submit]');
    await expect(page.locator('#app')).toBeVisible();
    // syncProfile() must set the avatar; the login handler no longer calls
    // setAv() directly (that call used to throw, see commit history).
    await expect(page.locator('#av')).not.toBeEmpty();
  });

  test('calling enter() twice does not re-register listeners or re-sync', async ({ page }) => {
    const terrainsCalls = [];
    page.on('request', (req) => {
      if (req.method() === 'GET' && req.url().includes('/api/terrains')) {
        terrainsCalls.push(req.url());
      }
    });
    await page.goto('/inzone-espace-client.html');
    await page.fill('#l-mail', 'investisseur@exemple.ma');
    await page.fill('#l-pass', 'demonstration');
    await page.click('#lf button[type=submit]');
    await expect(page.locator('#app')).toBeVisible();
    await page.waitForTimeout(500);

    const before = terrainsCalls.length;
    await page.evaluate(() => {
      // @ts-ignore - enter() is a page-global defined by inzone-espace-client.html
      if (typeof enter === 'function') enter('bord', false);
    });
    await page.waitForTimeout(500);
    expect(terrainsCalls.length - before).toBe(0);
  });
});
