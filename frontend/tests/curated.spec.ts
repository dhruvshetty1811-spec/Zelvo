import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

test.use({trace:'off'});
test('curated default runs a real matching pair and reproduces the target',async({page})=>{
  test.setTimeout(480_000);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await expect(page.getByLabel('Choose the journey')).toHaveValue('curated');
  await expect(page.locator('.control-route')).toHaveText('2.44 km / 10 junctions');
  await expect(page.getByText('560 ordinary vehicles scheduled')).toBeVisible();
  const created=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  const response=await created;expect(response.status()).toBe(201);
  const initial=await response.json();const id=initial.id;
  expect(initial.inputs.settings.corridor).toBe('curated');
  await page.getByLabel('Playback speed').selectOption('32');
  let receipt:any;
  await expect.poll(async()=>{
    try {
      receipt=await (await page.request.get(`/api/sessions/${id}/receipt`,{maxRetries:2})).json();
    } catch(error) {
      if(/ECONNRESET|ETIMEDOUT/.test(String(error)))return 'retrying receipt transport';
      throw error;
    }
    return receipt.status;
  },{timeout:420_000,intervals:[2000]}).toBe('complete');
  const b=receipt.results.baseline,z=receipt.results.zelvo;
  const saved=100*(b.journeys[0].journey_time_s-z.journeys[0].journey_time_s)/b.journeys[0].journey_time_s;
  expect(saved).toBeGreaterThanOrEqual(45);expect(saved).toBeLessThanOrEqual(55);
  expect(b.journeys[0].journey_time_s).toBeCloseTo(474.7,1);
  expect(z.journeys[0].journey_time_s).toBeCloseTo(245.5,1);
  expect(b.input_hashes.engine_source_sha256).toBe(z.input_hashes.engine_source_sha256);
  for(const result of [b,z]){
    expect(result.collision_events).toBe(0);expect(result.teleport_events).toBe(0);
    expect(result.metrics.safety_audit_errors).toBe(0);
    expect(result.metrics.ordinary.arrived).toBe(560);
    expect(Object.values(result.input_hashes)).toContain(receipt.inputs.network_sha256);
    expect(Object.values(result.input_hashes)).toContain(receipt.inputs.demand_sha256);
  }
  await expect(page.locator('.comparison-result')).toContainText('48.3% less travel time.',{timeout:30_000});
  await expect(page.locator('.run-details')).toContainText('simulated hospital destination');
  await page.screenshot({path:'../reports/curated-comparison-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'../reports/curated-comparison-mobile.png'});
  expect(errors).toEqual([]);
  await writeFile('../reports/curated-ui-replay.json',JSON.stringify({session:id,saved_percent:saved,inputs:receipt.inputs,results:receipt.results,finished_at_utc:receipt.finished_at_utc,scope:'Independent browser replay of a curated development preset; not population evidence'},null,2)+'\n');
});
