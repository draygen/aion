const { test, expect } = require('@playwright/test');

test('public health endpoint responds', async ({ request }) => {
  const response = await request.get('/api/system/public/health');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.ok).toBe(true);
  expect(body.service).toBe('jarvis');
});

test('landing page renders login UI', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Jarvis/i);
  await expect(page.locator('#login-overlay')).toHaveClass(/visible/);
  await expect(page.locator('#login-username')).toBeVisible();
  await expect(page.locator('#login-password')).toBeVisible();
  await expect(page.locator('#message-input')).toBeVisible();
});

test('user can sign in when credentials are provided', async ({ page }) => {
  const username = process.env.JARVIS_USERNAME;
  const password = process.env.JARVIS_PASSWORD;

  test.skip(!username || !password, 'Set JARVIS_USERNAME and JARVIS_PASSWORD to run the login smoke test.');

  await page.goto('/');
  await page.locator('#login-username').fill(username);
  await page.locator('#login-password').fill(password);
  await page.locator('#login-submit').click();

  await expect(page.locator('#login-overlay')).not.toHaveClass(/visible/);
  await expect(page.locator('#user-badge')).toContainText(new RegExp(username, 'i'));
  await expect(page.locator('#logout-btn')).toBeVisible();
});
