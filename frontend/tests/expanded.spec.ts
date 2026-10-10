import { expect, test } from '@playwright/test';
test.use({trace:'off'});
test.setTimeout(90_000);

test('expanded journey selector and immersive cameras at desktop and phone sizes',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#demo');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await expect(page.getByLabel('Choose the journey')).toHaveValue('curated');
  await expect(page.locator('.control-route')).toHaveText('2.44 km / 10 junctions');
  await expect(page.getByText(/simulated hospital destination/)).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('expanded');
  await expect(page.locator('.control-route')).toHaveText('6.15 km / 13 junctions');
  await page.getByRole('button',{name:'Heavy',exact:true}).click();
  await expect(page.getByText('1200 ordinary vehicles scheduled')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('reference');
  await expect(page.locator('.control-route')).toHaveText('0.91 km / 3 junctions');
  await expect(page.getByText('600 ordinary vehicles scheduled')).toBeVisible();
  await page.getByLabel('Choose the journey').selectOption('expanded');
  await expect(page.locator('.control-route')).toHaveText('6.15 km / 13 junctions');
  await page.screenshot({path:'../reports/expanded-setup-desktop.png',fullPage:true});

  // Camera/layout fixture only. Actual physics and paired outcomes are validated
  // independently in results/expanded-validation, never inferred from this fixture.
  const network=await (await page.request.get('/api/network?corridor=expanded')).json();
  await page.route('**/api/sessions',route=>route.fulfill({status:201,json:{id:'camera-fixture'}}));
  await page.route('**/api/sessions/camera-fixture',route=>route.fulfill({json:{status:'cancelled'}}));
  await page.routeWebSocket('**/api/sessions/camera-fixture/stream',socket=>{
    for(const side of ['baseline','zelvo'])socket.send(JSON.stringify({type:'frames',side,frames:[{
      time_s:60,vehicles:[['ambulance-0',...network.origin,0,0,'ambulance']],signals:{},collisions:0,teleports:0,
      ambulance:{departed:true,arrived:false,departure_s:60,arrival_s:null,travel_s:0,stopped_s:0,red_wait_s:0,speed_mps:0,stops:0,position:network.origin,distance_m:0}
    }]}));
  });
  await page.getByRole('button',{name:'Run comparison',exact:true}).click();
  await expect(page.locator('canvas')).toHaveCount(2);
  await expect(page.locator('.baseline .camera-tools button').first()).toHaveAttribute('aria-pressed','true');
  const pixels=()=>page.locator('.baseline canvas').evaluate(element=>{
    const c=element as HTMLCanvasElement;const p=c.getContext('2d')!.getImageData(0,0,c.width,c.height).data;
    let hash=0;for(let i=0;i<p.length;i+=160)hash=(hash*31+p[i])>>>0;return hash;
  });
  const followed=await pixels();
  await page.locator('.baseline').getByRole('button',{name:'Entire route',exact:true}).click();
  await expect.poll(pixels).not.toBe(followed);
  const overview=await pixels();
  await page.getByRole('button',{name:'Zoom in baseline map'}).click();
  await expect.poll(pixels).not.toBe(overview);
  const box=await page.locator('.baseline canvas').boundingBox();
  await page.mouse.move(box!.x+box!.width*.4,box!.y+box!.height*.55);
  await page.mouse.down();await page.mouse.move(box!.x+box!.width*.4+70,box!.y+box!.height*.55+20);await page.mouse.up();
  await expect(page.locator('.baseline').getByRole('button',{name:'Entire route',exact:true})).toHaveAttribute('aria-pressed','false');
  await page.locator('.baseline').getByRole('button',{name:'Follow ambulance',exact:true}).click();
  await page.getByLabel('Playback speed').selectOption('32');
  await page.screenshot({path:'../reports/expanded-camera-desktop.png'});
  for(const width of [390,360]){
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    for(const side of ['baseline','zelvo']){
      const panel=page.locator(`.${side}`);
      await expect(panel.getByRole('button',{name:'Follow ambulance',exact:true})).toBeVisible();
      const heading=await panel.locator('.panel-header').boundingBox(),tools=await panel.locator('.camera-tools').boundingBox();
      expect(tools!.y).toBeGreaterThan(heading!.y+heading!.height);
    }
    const coverage=await page.locator('canvas').evaluateAll(elements=>elements.reduce((n,e)=>{const r=e.getBoundingClientRect();return n+r.width*r.height;},0)/(innerWidth*innerHeight));
    expect(coverage).toBeGreaterThan(.99);
    await page.screenshot({path:`../reports/expanded-camera-${width}.png`});
  }
  expect(errors).toEqual([]);
  await page.getByRole('button',{name:'Back to home',exact:true}).click();
});
