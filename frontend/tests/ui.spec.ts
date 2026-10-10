import { expect, test } from '@playwright/test';

test('landing, controls, and mobile layouts remain readable',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await page.evaluate(()=>document.fonts.ready);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await expect(page.getByRole('heading',{name:'2 in 10.'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'An emergency cannot wait for traffic.'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Turn the signal green before the ambulance gets there.'})).toBeVisible();
  await expect(page.locator('.opening-statement')).toContainText('Patients in ambulances die');
  await expect(page.getByRole('link',{name:/RADHEE/})).toHaveAttribute('href','https://radhee.com/projects/give-way-to-ambulance/');
  await expect(page.getByText('46.9',{exact:false}).first()).toBeVisible();
  await expect(page.getByText('Ambulance corridor replay',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Pause corridor preview'}).click();
  await expect(page.getByRole('button',{name:'Play corridor preview'})).toBeVisible();
  await page.getByRole('button',{name:'Restart corridor preview'}).click();
  await expect.poll(()=>page.locator('.hero-map canvas').evaluate(element=>{
    const canvas=element as HTMLCanvasElement;
    const pixels=canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data;
    let red=false,green=false;
    for(let i=0;i<pixels.length;i+=4){
      if(pixels[i]===220&&pixels[i+1]===38&&pixels[i+2]===38)red=true;
      if(pixels[i]===22&&pixels[i+1]===163&&pixels[i+2]===74)green=true;
    }
    return {red,green};
  })).toEqual({red:true,green:true});
  await page.getByRole('button',{name:'Prepare the next junction.'}).click();
  await expect(page.locator('.method-network')).toHaveClass(/phase-1/);
  await expect(page.getByText('It estimates when the ambulance will reach the next junction, then prepares the signals so waiting traffic can move ahead.')).toBeVisible();
  await page.getByRole('button',{name:'Make room along the route.'}).click();
  await expect(page.locator('.method-network')).toHaveClass(/phase-2/);
  await page.getByRole('button',{name:'Read the road.'}).click();
  await page.getByText('What this result does').click();
  await expect(page.getByRole('link',{name:'Download measured evidence'})).toBeVisible();
  await page.getByText('What this result does').click();
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:'../reports/ui-landing-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Run the live comparison'}).click();
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await expect(page.getByRole('heading',{name:'First, set the scene.'})).toBeVisible();
  await expect(page.locator('canvas')).toHaveCount(0);
  await page.getByRole('button',{name:'Heavy',exact:true}).click();
  await expect(page.getByText('600 ordinary vehicles scheduled')).toBeVisible();
  await page.getByRole('button',{name:'More settings'}).click();
  await page.getByLabel('Sensor delay').selectOption('6');
  await page.getByRole('button',{name:'Restore default settings'}).click();
  await expect(page.getByLabel('Sensor delay')).toHaveValue('0');
  await page.screenshot({path:'../reports/ui-demo-idle-desktop.png',fullPage:true});
  for(const width of [390,360]) {
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:`../reports/ui-demo-mobile-${width}.png`,fullPage:true});
  }
  await page.goto('/');
  await page.screenshot({path:'../reports/ui-landing-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('a changed scenario starts a fresh pair, blocks overlap, and can be stopped',async({page})=>{
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Heavy',exact:true}).click();
  await page.getByLabel('Random seed').fill('43');
  await page.getByRole('button',{name:'More settings'}).click();
  await page.getByLabel('Sensor delay').selectOption('2');
  const created=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  const response=await created;expect(response.status()).toBe(201);const session=await response.json();
  expect(session.inputs.ordinary_vehicle_count).toBe(600);
  expect(session.inputs.settings.seed).toBe(43);
  expect(session.inputs.settings.observation_delay_s).toBe(2);
  await expect(page.getByRole('main',{name:'Full screen corridor comparison'})).toBeVisible();
  await expect(page.locator('.site-header')).toBeHidden();
  await expect(page.getByRole('button',{name:'Change settings'})).toHaveCount(0);
  const controlBounds=await page.locator('.playback-toolbar').boundingBox();
  const panelBounds=await page.locator('.zelvo .panel-header').boundingBox();
  expect(controlBounds&&panelBounds&&controlBounds.y+controlBounds.height<panelBounds.y).toBeTruthy();
  await expect(page.locator('canvas')).toHaveCount(2);
  const coverage=await page.locator('canvas').evaluateAll(elements=>elements.reduce((sum,element)=>{const r=element.getBoundingClientRect();return sum+r.width*r.height;},0)/(innerWidth*innerHeight));
  expect(coverage).toBeGreaterThan(.99);
  expect(await page.locator('.comparison-stage').evaluate(element=>{
    const rect=element.getBoundingClientRect();
    return rect.x===0&&rect.y===0&&Math.abs(rect.width-innerWidth)<1&&Math.abs(rect.height-innerHeight)<1;
  })).toBeTruthy();
  await expect(page.locator('.map-empty')).toHaveCount(0,{timeout:120_000});
  await page.screenshot({path:'../reports/ui-comparison-fullscreen-desktop.png'});
  for(const width of [390,360]) {
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    expect(await page.locator('canvas').evaluateAll(elements=>elements.every(element=>{
      const rect=element.getBoundingClientRect();return rect.width>250&&rect.height>=100&&rect.bottom<=innerHeight+1;
    }))).toBeTruthy();
    await page.screenshot({path:`../reports/ui-comparison-fullscreen-mobile-${width}.png`});
  }
  const overlap=await page.request.post('/api/sessions',{data:{}});expect(overlap.status()).toBe(409);
  await page.getByRole('button',{name:'Stop',exact:true}).click();
  await expect(page.getByRole('button',{name:'Run comparison',exact:true})).toBeEnabled({timeout:30_000});
  await expect(page.getByRole('heading',{name:'First, set the scene.'})).toBeFocused();
  await expect(page.locator('.comparison-stage')).toHaveCount(0);
  await expect(page.locator('.site-header')).toBeVisible();
  const receipt=await (await page.request.get(`/api/sessions/${session.id}/receipt`)).json();
  expect(receipt.status).toBe('cancelled');
  expect(receipt.partial_run).toBe(true);
  expect(Object.values(receipt.worker_exit_codes).every(code=>code!==null)).toBe(true);
  await expect(page.getByText('The comparison needs attention.')).not.toBeVisible();
});

test('reference UI starts two real workers and reproduces measured arrivals',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  const created=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  const response=await created;expect(response.status()).toBe(201);const session=await response.json();
  await page.getByLabel('Playback speed').selectOption('16');
  await expect(page.getByText('67.6 seconds saved.',{exact:false})).toBeVisible({timeout:150_000});
  await page.screenshot({path:'../reports/ui-demo-arrivals.png',fullPage:true});
  await expect(page.getByText('Comparison complete',{exact:true})).toBeVisible({timeout:180_000});
  const receipt=await (await page.request.get(`/api/sessions/${session.id}/receipt`)).json();
  expect(receipt.status).toBe('complete');
  expect(receipt.results.baseline.journeys[0].journey_time_s).toBe(144.2);
  expect(receipt.results.zelvo.journeys[0].journey_time_s).toBe(76.6);
  expect(receipt.results.baseline.input_hashes.engine_source_sha256).toBe(receipt.results.zelvo.input_hashes.engine_source_sha256);
  expect(receipt.inputs.ordinary_vehicle_count).toBe(300);
  for(const side of ['baseline','zelvo']) {
    expect(receipt.results[side].collision_events).toBe(0);
    expect(receipt.results[side].metrics.safety_audit_errors).toBe(0);
    expect(receipt.results[side].metrics.ordinary.arrived).toBe(300);
    expect(receipt.frames[side]).toBeGreaterThan(300);
  }
  await page.getByRole('link',{name:'Download run receipt'}).isVisible();
  await page.screenshot({path:'../reports/ui-demo-complete.png',fullPage:true});
  expect(await page.locator('canvas').evaluateAll(elements=>elements.every(element=>{
    const canvas=element as HTMLCanvasElement, data=canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data;
    return canvas.width>0&&canvas.height>0&&data.some((value,index)=>index%4===3&&value===255);
  }))).toBeTruthy();
  expect(errors).toEqual([]);
});

test('completed demo offers a readable way home and exits fullscreen',async({page})=>{
  // Exercise completed UI state without allocating simulation workers.
  await page.route('**/api/sessions',route=>route.fulfill({status:201,json:{id:'ui-completed-demo'}}));
  await page.routeWebSocket('**/api/sessions/ui-completed-demo/stream',socket=>{
    for(const [side,travel] of [['baseline',144.2],['zelvo',76.6]] as const) {
      socket.send(JSON.stringify({type:'frames',side,frames:[{time_s:60,vehicles:[],signals:{},collisions:0,teleports:0,ambulance:{departed:true,arrived:true,departure_s:60,arrival_s:60+travel,travel_s:travel,stopped_s:0,red_wait_s:0,speed_mps:0,stops:0,position:null,distance_m:913}}]}));
    }
    socket.send(JSON.stringify({type:'finished',id:'ui-completed-demo',status:'complete',errors:{},results:{},inputs:{settings:{dispatch_s:60}}}));
  });
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  const home=page.getByRole('button',{name:'Back to home',exact:true});
  await expect(home).toBeVisible();
  await expect(page.getByText('67.6 seconds saved.',{exact:false})).toBeVisible();
  await page.screenshot({path:'../reports/ui-demo-back-home-desktop.png'});
  await page.setViewportSize({width:360,height:844});
  expect(await home.evaluate(element=>{const r=element.getBoundingClientRect();return r.x>=0&&r.right<=innerWidth&&r.y>=0&&r.bottom<=innerHeight;})).toBeTruthy();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'../reports/ui-demo-back-home-mobile.png'});
  await home.click();
  await expect(page.getByRole('heading',{name:'2 in 10.'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'2 in 10.'})).toBeFocused();
  await expect(page.locator('.comparison-stage')).toHaveCount(0);
  await expect(page.locator('.site-header')).toBeVisible();
  expect(await page.evaluate(()=>document.fullscreenElement===null&&document.body.style.overflow!=='hidden'&&window.scrollY===0)).toBeTruthy();
});

for(const width of [1440,360])test(`home button is available before any arrivals at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:844});
  await page.route('**/api/sessions',route=>route.fulfill({status:201,json:{id:'ui-pending-demo'}}));
  await page.route('**/api/sessions/ui-pending-demo',route=>route.fulfill({json:{status:'cancelled'}}));
  await page.routeWebSocket('**/api/sessions/ui-pending-demo/stream',()=>{});
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  await expect(page.locator('.comparison-result')).toBeHidden();
  const home=page.getByRole('button',{name:'Back to home',exact:true});
  await expect(home).toBeVisible();
  const homeBox=await home.boundingBox(),panelBox=await page.locator('.baseline .panel-header').boundingBox();
  expect(homeBox&&panelBox&&homeBox.y+homeBox.height<panelBox.y).toBeTruthy();
  await page.screenshot({path:`../reports/ui-back-home-pending-${width}.png`});
  const stopped=page.waitForRequest(r=>r.url().endsWith('/api/sessions/ui-pending-demo')&&r.method()==='DELETE');
  await home.click();
  await stopped;
  await expect(page.getByRole('heading',{name:'2 in 10.'})).toBeVisible();
  await expect(page.locator('.comparison-stage')).toHaveCount(0);
  expect(await page.evaluate(()=>!document.fullscreenElement&&document.body.style.overflow!=='hidden')).toBeTruthy();
});
