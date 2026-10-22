import { expect, test } from '@playwright/test';

test('hosted live engine exposes real corridor demand and percentage controls', async ({ page }) => {
  test.skip(!process.env.ZELVO_TEST_BASE_URL?.includes('onrender.com'), 'Hosted deployment check');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#demo');
  await expect(page.getByText('Simulation engine connected')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.control-route')).toHaveText('2.44 km / 10 junctions');
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.locator('.control-route')).toHaveText('0.91 km / 3 junctions');
  await page.getByRole('slider', { name: 'Traffic density' }).fill('37');
  await expect(page.getByText('111 ordinary vehicles scheduled')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run comparison', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../reports/render-live-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});
