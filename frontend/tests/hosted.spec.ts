import { expect, test } from '@playwright/test';

test('hosted live engine exposes real corridor demand and percentage controls', async ({ page }) => {
  test.skip(!/onrender\.com|zelvo-wine\.vercel\.app/.test(process.env.ZELVO_TEST_BASE_URL??''), 'Hosted deployment check');
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

test('hosted frontend completes a fresh comparison through its configured backend', async ({ page }) => {
  test.skip(process.env.ZELVO_TEST_LIVE!=='1', 'Explicit native simulation verification');
  test.setTimeout(660_000);
  const streamFrames: Record<string, number> = { baseline: 0, zelvo: 0 };
  page.on('websocket', socket => socket.on('framereceived', frame => {
    try {
      const message=JSON.parse(String(frame.payload));
      if(message.type==='frames')streamFrames[message.side]+=message.frames.length;
    } catch { /* Ignore protocol heartbeats. */ }
  }));
  await page.goto('/#demo');
  await expect(page.getByText('Simulation engine connected')).toBeVisible({ timeout: 90_000 });
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.locator('.control-route')).toHaveText('0.91 km / 3 junctions');
  await page.getByRole('slider', { name: 'Traffic density' }).fill('37');
  await page.getByLabel('Random seed').fill('17');
  const created=page.waitForResponse(response=>response.url().endsWith('/api/sessions')&&response.request().method()==='POST');
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  const response=await created;
  expect(response.status()).toBe(201);
  const session=await response.json();
  expect(session.inputs.ordinary_vehicle_count).toBe(111);
  const backend=new URL(response.url()).origin;
  await page.getByLabel('Playback speed').selectOption('32');
  let receipt: any;
  await expect.poll(async()=>{
    receipt=await (await page.request.get(`${backend}/api/sessions/${session.id}/receipt`)).json();
    return receipt.status;
  },{timeout:600_000,intervals:[5000]}).toBe('complete');
  for(const side of ['baseline','zelvo']){
    expect(streamFrames[side]).toBeGreaterThan(0);
    expect(receipt.results[side].journeys[0].completed).toBeTruthy();
    expect(Object.values(receipt.results[side].input_hashes)).toContain(receipt.inputs.demand_sha256);
    expect(receipt.results[side].collision_events).toBe(0);
    expect(receipt.results[side].teleport_events).toBe(0);
    expect(receipt.results[side].metrics.safety_audit_errors).toBe(0);
  }
  await expect(page.locator('.comparison-result')).toContainText('seconds saved.',{timeout:30_000});
  await page.screenshot({path:'../reports/vercel-live-comparison.png',fullPage:true});
});
