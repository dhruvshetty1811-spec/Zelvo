import { expect, test } from '@playwright/test';

test('percentage slider submits real demand settings and fits mobile', async ({ page }) => {
  await page.route('**/api/network?*', route => route.fulfill({ json: {
    roads: [], signals: [], route: [], route_length_m: 2442.08, ordinary_vehicle_count: 560,
  } }));
  await page.route('**/api/sessions', route => route.fulfill({ status: 422, json: { detail: 'Test completed' } }));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Rush-hour preset selected' })).toBeDisabled();
  const slider = page.getByRole('slider', { name: 'Traffic density' });
  await expect(slider).toHaveValue('100');
  await slider.fill('137');
  await expect(page.getByText('767 ordinary vehicles scheduled')).toBeVisible();
  await page.getByRole('button', { name: 'Use rush-hour preset' }).click();
  await expect(slider).toHaveValue('100');
  await expect(page.getByText('560 ordinary vehicles scheduled')).toBeVisible();
  await slider.fill('137');
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../reports/density-slider-mobile.png' });
  const request = page.waitForRequest(r => r.url().endsWith('/api/sessions') && r.method() === 'POST');
  await page.getByRole('button', { name: 'Run comparison', exact: true }).click();
  expect((await request).postDataJSON().density_percent).toBe(137);
});

test('published evidence explains the calculation', async ({ page }) => {
  await page.goto('/');
  await page.locator('.evidence-details summary').click();
  await expect(page.locator('.evidence-disclosure')).toContainText('(67.6 ÷ 144.2) × 100 = 46.8793%');
  await expect(page.locator('.evidence-disclosure')).toContainText('not an average across traffic densities');
});

test('unavailable engine cannot fall back to recorded outcomes', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.route('**/api/network?*', route => route.fulfill({ status: 503, json: { detail: 'Offline' } }));
  await page.goto('/#demo');
  await expect(page.getByText('Simulation engine offline')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run comparison', exact: true })).toBeDisabled();
  expect(requests.some(url => url.includes('/hosted-demo/'))).toBeFalsy();
  await expect(page.locator('.comparison-result')).toHaveCount(0);
});
