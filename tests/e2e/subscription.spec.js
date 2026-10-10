const { test, expect } = require('@playwright/test');

// Full Veille/Veille Pro journey: subscribe, admin marks the invoice paid,
// the subscription activates and gated content unlocks for the client.
// Each test gets its own fresh browser context, but they share the one
// backend instance started for the whole file (webServer wipes the DB
// once per `npx playwright test` run, not per test) -- so tests run in
// order and build on each other's state, same as the manual run they
// formalize.

test.describe.configure({ mode: 'serial' });

async function loginAsClient(page) {
  await page.addInitScript(() => {
    try { localStorage.setItem('inz-onb-seen', '1'); } catch (_) {}
  });
  await page.goto('/inzone-espace-client.html');
  await page.fill('#l-mail', 'investisseur@exemple.ma');
  await page.fill('#l-pass', 'demonstration');
  await page.click('#lf button[type=submit]');
  await expect(page.locator('#app')).toBeVisible();
}

async function loginAsAdmin(page) {
  await page.goto('/inzone-admin.html');
  await page.fill('input[type=password]', 'demonstration');
  await page.click('button:has-text("Se connecter")');
  await expect(page.locator('#app')).toBeVisible();
}

test('client accepts the non-circumvention engagement and subscribes to Veille Pro', async ({ page }) => {
  await loginAsClient(page);

  await page.click('[data-go="compte"]');
  await expect(page.locator('#ncc-text')).not.toBeEmpty();
  await expect(page.locator('#ncc-text')).not.toContainText('VALIDER');
  await page.check('#ncc-check');
  await page.click('#ncc-accept');
  await expect(page.locator('#ncc-msg')).toContainText('Accepté le');

  await page.click('[data-go="abo"]');
  await page.click('[data-subscribe="Veille Pro"][data-duree2="6"]');
  await expect(page.locator('#abo-msg')).toContainText('Abonnement créé');

  const invoiceRow = page.locator('#fac-rows tr').first();
  await expect(invoiceRow).toContainText('Veille Pro');
  await expect(invoiceRow).toContainText('Émise');
});

test('admin marks the invoice paid and the Abonnés table reflects it immediately', async ({ page }) => {
  await loginAsAdmin(page);
  await page.click('[data-go="demandes"]');

  const payButton = page.locator('[data-fp]').first();
  await expect(payButton).toBeVisible();
  await payButton.click();

  await page.click('[data-go="clients"]');
  const subRow = page.locator('#abo-rows-admin tr').first();
  await expect(subRow).toContainText('Payé');
});

test('subscription is active for the client and Veille content unlocks', async ({ page }) => {
  await loginAsClient(page);
  await page.click('[data-go="abo"]');
  await expect(page.locator('#abo-formule')).toContainText('Veille Pro');
  await expect(page.locator('#abo-sub')).toContainText('Abonnement actif');

  await page.click('[data-go="veille"]');
  await expect(page.locator('#vl-locked')).toBeHidden();
});

test('mise en relation request succeeds once subscribed and engagement accepted', async ({ page }) => {
  await loginAsClient(page);
  await page.click('[data-go="terrains"]');

  const target = 'INZ-ATT-002';
  // Two matching buttons exist (desktop table + mobile card); only one is
  // visible depending on viewport, so wait for attachment, not visibility,
  // then click via evaluate same as below.
  await page.waitForSelector(`[data-fiche="${target}"]`, { state: 'attached' });
  await page.evaluate((ref) => {
    document.querySelector(`[data-fiche="${ref}"]`).click();
  }, target);
  await expect(page.locator('#f-relation')).toBeVisible();
  await expect(page.locator('#f-relation')).toBeEnabled();

  // The click triggers a confirm() (transparency notice) then, once
  // accepted, an async request followed by an alert() with the result.
  const dialogs = [];
  page.on('dialog', async (d) => {
    dialogs.push({ type: d.type(), message: d.message() });
    await d.accept();
  });
  await page.click('#f-relation');
  await expect.poll(() => dialogs.some((d) => d.type === 'alert')).toBe(true);

  expect(dialogs[0].type).toBe('confirm');
  const alertDialog = dialogs.find((d) => d.type === 'alert');
  expect(alertDialog.message).toContain('Demande envoyée');
});
