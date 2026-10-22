import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function mockNetwork(page: import('@playwright/test').Page) {
  const network=JSON.parse(await readFile('src/data/network.json','utf8'));
  await page.route('**/api/network?*', route=>route.fulfill({json:{...network,ordinary_vehicle_count:300}}));
}

const frame=(travel: number, arrived=false)=>({time_s:60+travel,vehicles:[],signals:{},collisions:0,teleports:0,
  ambulance:{departed:true,arrived,departure_s:60,arrival_s:arrived?60+travel:null,travel_s:travel,
    stopped_s:0,red_wait_s:0,speed_mps:0,stops:0,position:null,distance_m:0}});

test('closed socket resumes over HTTP without duplicating frames or restarting the run',async({page})=>{
  await mockNetwork(page);
  let creates=0,settings:any;
  await page.route('**/api/sessions',async route=>{
    creates++;settings=route.request().postDataJSON();
    await route.fulfill({status:201,json:{id:'recover',status:'running'}});
  });
  await page.routeWebSocket('**/api/sessions/recover/stream', socket=>{
    socket.send(JSON.stringify({type:'frames',side:'baseline',frames:[frame(0)]}));
    setTimeout(()=>socket.close({code:1001,reason:'Connection interrupted'}),100);
  });
  const offsets:string[]=[];
  const result=(time:number)=>({status:'completed',journeys:[{completed:true,journey_time_s:time}],
    collision_events:0,teleport_events:0,metrics:{safety_audit_errors:0,ordinary:{arrived:111}}});
  await page.route('**/api/sessions/recover/updates?*',async route=>{
    offsets.push(new URL(route.request().url()).search);
    if(offsets.length===1){await route.fulfill({status:503,json:{detail:'Temporary outage'}});return;}
    await route.fulfill({json:{status:'complete',frames:{baseline:[frame(100,true)],zelvo:[frame(0),frame(50,true)]},
      finished:{id:'recover',status:'complete',errors:{},inputs:{settings,ordinary_vehicle_count:111},
        results:{baseline:result(100),zelvo:result(50)}}}});
  });
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  await page.getByLabel('Playback speed').selectOption('32');
  await expect(page.locator('.comparison-result')).toContainText('50.0% less travel time.',{timeout:20_000});
  expect(creates).toBe(1);
  expect(offsets).toHaveLength(2);
  expect(offsets.every(offset=>offset.includes('baseline_after=1')&&offset.includes('zelvo_after=0'))).toBeTruthy();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('button',{name:'Back to settings',exact:true}).click();
  await expect(page.getByRole('button',{name:'Run comparison',exact:true})).toBeEnabled();
});

test('a lost server session returns to setup with a clear error and a usable new-run button',async({page})=>{
  await mockNetwork(page);
  await page.route('**/api/sessions',route=>route.fulfill({status:201,json:{id:'lost',status:'running'}}));
  await page.routeWebSocket('**/api/sessions/lost/stream',socket=>socket.close({code:1001}));
  await page.route('**/api/sessions/lost/updates?*',route=>route.fulfill({status:404,json:{detail:'Comparison not found'}}));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('This run is no longer available');
  await expect(page.getByRole('heading',{name:'First, set the scene.'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run comparison',exact:true})).toBeEnabled();
  await expect(page.locator('.comparison-result')).toHaveCount(0);
});

test('Stop succeeds locally when the server has already lost the session',async({page})=>{
  await mockNetwork(page);
  await page.route('**/api/sessions',route=>route.fulfill({status:201,json:{id:'gone',status:'running'}}));
  await page.routeWebSocket('**/api/sessions/gone/stream',socket=>socket.onMessage(()=>{}));
  await page.route('**/api/sessions/gone',route=>route.fulfill({status:404,json:{detail:'Not found'}}));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  await page.getByRole('button',{name:'Stop',exact:true}).click();
  await expect(page.getByRole('button',{name:'Run comparison',exact:true})).toBeEnabled();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
