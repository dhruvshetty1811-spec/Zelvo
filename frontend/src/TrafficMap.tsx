import { useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import type { Network, Side } from './types';
import type { Buffers } from './useLive';
import { frameAt } from './useLive';

export function TrafficMap({network,side,buffers,playhead,interactive=true}:{network:Network;side:Side;buffers:MutableRefObject<Buffers>;playhead:MutableRefObject<number>;interactive?:boolean}) {
  const canvas=useRef<HTMLCanvasElement>(null);
  const camera=useRef({mode:(interactive?'follow':'overview') as 'follow'|'overview'|'free',zoom:1,panX:0,panY:0});
  const [mode,setMode]=useState(interactive?'follow':'overview');
  const choose=(value:'follow'|'overview')=>{camera.current={mode:value,zoom:1,panX:0,panY:0};setMode(value);};
  const changeZoom=(factor:number)=>{camera.current.zoom=Math.max(.5,Math.min(8,camera.current.zoom*factor));};
  const drag=useRef<{x:number;y:number}|null>(null);

  useEffect(()=>{
    const element=canvas.current!; const ctx=element.getContext('2d')!;
    const staticLayer=document.createElement('canvas');const background=staticLayer.getContext('2d')!;
    let width=0,height=0,dpr=1,scale=1,offsetX=0,offsetY=0,raf=0,baseScale=1,baseX=0,baseY=0;
    const [minX,minY,maxX,maxY]=network.bounds;
    const project=(p:number[])=>[offsetX+(p[0]-minX)*scale,offsetY+(maxY-p[1])*scale];
    const line=(c:CanvasRenderingContext2D,shape:number[][])=>{c.beginPath();shape.forEach((p,i)=>{const [x,y]=project(p);if(i)c.lineTo(x,y);else c.moveTo(x,y);});};
    const roundRect=(c:CanvasRenderingContext2D,x:number,y:number,w:number,h:number,r:number)=>{c.beginPath();c.roundRect(x,y,w,h,r);};
    const roadPaths=network.roads.map(road=>{
      const path=new Path2D();road.shape.forEach(([x,y],i)=>{if(i)path.lineTo(x,y);else path.moveTo(x,y);});
      const xs=road.shape.map(p=>p[0]),ys=road.shape.map(p=>p[1]);
      return {...road,path,box:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]};
    });
    const resize=()=>{
      const rect=element.getBoundingClientRect();width=rect.width;height=rect.height;dpr=Math.min(devicePixelRatio||1,2);
      element.width=staticLayer.width=Math.round(width*dpr);element.height=staticLayer.height=Math.round(height*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);background.setTransform(dpr,0,0,dpr,0,0);
      scale=Math.min((width-44)/(maxX-minX),(height-70)/(maxY-minY));offsetX=(width-(maxX-minX)*scale)/2;offsetY=(height-(maxY-minY)*scale)/2;
      background.fillStyle='#e9e9e9';background.fillRect(0,0,width,height);
      // A quiet map grid, locally rendered from the actual OSM road geometry.
      background.strokeStyle='#dedede';background.lineWidth=.6;
      for(let x=0;x<width;x+=32){background.beginPath();background.moveTo(x,0);background.lineTo(x,height);background.stroke();}
      for(let y=0;y<height;y+=32){background.beginPath();background.moveTo(0,y);background.lineTo(width,y);background.stroke();}
      baseScale=scale;baseX=offsetX;baseY=offsetY;
      background.lineJoin='round';background.lineCap='round';
      for(const road of network.roads){line(background,road.shape);background.strokeStyle=road.internal?'#dcdcdc':'#cacaca';background.lineWidth=road.internal?Math.max(.5,2*scale):Math.max(.9,road.lanes*3.2*scale+1);background.stroke();}
      for(const road of network.roads){if(road.internal)continue;line(background,road.shape);background.strokeStyle='#ffffff';background.lineWidth=Math.max(.45,road.lanes*3.2*scale);background.stroke();}
    };
    const observer=new ResizeObserver(resize);observer.observe(element);resize();
    const draw=()=>{
      // During a route/layout change a canvas can briefly measure zero. Keep
      // the animation alive until layout settles instead of throwing once.
      if(width<=0||height<=0||staticLayer.width===0||staticLayer.height===0){resize();raf=requestAnimationFrame(draw);return;}
      const [a,b,alpha]=frameAt(buffers.current[side],playhead.current);
      const cam=camera.current;
      const position=a?.ambulance.position??network.origin;
      const nextPosition=b?.ambulance.position??position;
      const center=cam.mode==='follow'?[position[0]+(nextPosition[0]-position[0])*alpha,position[1]+(nextPosition[1]-position[1])*alpha]:[(minX+maxX)/2,(minY+maxY)/2];
      // Both worlds use the same metres-per-pixel scale in follow mode.
      scale=(cam.mode==='follow'?Math.min(width,height)/650:baseScale)*cam.zoom;
      offsetX=width/2-(center[0]-minX)*scale+cam.panX;
      offsetY=height/2-(maxY-center[1])*scale+cam.panY;
      const factor=scale/baseScale;
      ctx.fillStyle='#e9e9e9';ctx.fillRect(0,0,width,height);
      if(factor<=2){ctx.drawImage(staticLayer,offsetX-baseX*factor,offsetY-baseY*factor,width*factor,height*factor);}
      else {
        // Draw only visible road vectors when zoomed in, avoiding a blurred
        // enlargement of the overview bitmap and huge offscreen canvases.
        const left=minX-offsetX/scale,right=left+width/scale;
        const top=maxY+offsetY/scale,bottom=top-height/scale;
        const visible=roadPaths.filter(r=>r.box[2]>=left&&r.box[0]<=right&&r.box[3]>=bottom&&r.box[1]<=top);
        ctx.save();ctx.setTransform(dpr*scale,0,0,-dpr*scale,dpr*(offsetX-minX*scale),dpr*(offsetY+maxY*scale));
        ctx.lineJoin='round';ctx.lineCap='round';
        for(const road of visible){ctx.strokeStyle=road.internal?'#dcdcdc':'#cacaca';ctx.lineWidth=road.internal?2:road.lanes*3.2+2;ctx.stroke(road.path);}
        for(const road of visible){if(road.internal)continue;ctx.strokeStyle='#ffffff';ctx.lineWidth=road.lanes*3.2;ctx.stroke(road.path);}
        ctx.restore();
      }
      ctx.lineJoin='round';ctx.lineCap='round';
      for(const shape of network.route){line(ctx,shape);ctx.strokeStyle=side==='zelvo'?'#20202026':'#58585818';ctx.lineWidth=13;ctx.stroke();line(ctx,shape);ctx.strokeStyle=side==='zelvo'?'#202020':'#787878';ctx.lineWidth=4;ctx.stroke();}
      for(const [p,label] of [[network.origin,'Dispatch'],[network.hospital,network.destination_label??'Hospital']] as [number[],string][]){const [x,y]=project(p);if(x<0||x>width||y<0||y>height)continue;ctx.fillStyle='#202020';ctx.fillRect(x-7,y-7,14,14);ctx.fillStyle='#fff';ctx.fillRect(x-4,y-1,8,2);ctx.fillRect(x-1,y-4,2,8);ctx.font='600 11px Arial';ctx.textAlign='center';ctx.fillStyle='#202020';ctx.fillText(label,x,y-16);}

      if(a) {
        const next=new Map(b?.vehicles.map(v=>[v[0],v]));
        for(const signal of network.signals){
          const [x,y]=project(signal.position),state=a.signals[signal.id];
          const code=state==='G'||state==='g'?'G':state==='y'||state==='Y'?'Y':state==='r'||state==='R'?'R':'?';
          const radius=width<450?8:11;
          ctx.fillStyle=code==='G'?'#16a34a':code==='Y'?'#f59e0b':code==='R'?'#dc2626':'#858585';ctx.strokeStyle='#202020';ctx.lineWidth=2;
          ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fill();ctx.stroke();
          ctx.fillStyle=code==='Y'?'#202020':'#ffffff';ctx.font=`700 ${width<450?8:11}px Arial`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(code,x,y+.5);ctx.textBaseline='alphabetic';
        }
        for(const vehicle of a.vehicles){
          const n=next.get(vehicle[0])||vehicle;
          const p=[vehicle[1]+(n[1]-vehicle[1])*alpha,vehicle[2]+(n[2]-vehicle[2])*alpha];
          const [x,y]=project(p);if(x<0||x>width||y<0||y>height)continue;
          const ambulance=vehicle[5]==='ambulance';
          const angle=vehicle[3]+(((n[3]-vehicle[3]+540)%360)-180)*alpha;
          ctx.save();ctx.translate(x,y);ctx.rotate(angle*Math.PI/180);
          ctx.scale(width<450?.78:1,width<450?.78:1);
          if(ambulance){ctx.shadowColor='#23232330';ctx.shadowBlur=8;ctx.fillStyle='#232323';roundRect(ctx,-10,-18,20,36,5);ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#b3b3b3';roundRect(ctx,-6,-12,12,6,1);ctx.fill();ctx.fillStyle='#ffffff';ctx.fillRect(-6,1,12,3);ctx.fillRect(-1.5,-3,3,11);ctx.fillStyle='#202020';ctx.fillRect(-7,-17,14,3);ctx.fillRect(-6,13,12,2);}else{ctx.fillStyle=vehicle[4]<.1?'#939393':vehicle[5]==='bus'?'#696969':'#818181';const w=vehicle[5]==='bike'?3:5.5,h=vehicle[5]==='bus'?15:10;roundRect(ctx,-w/2,-h/2,w,h,1.5);ctx.fill();}ctx.restore();
        }
        if(a.ambulance.arrived){const [x,y]=project(network.hospital);ctx.fillStyle='#202020';ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x-4,y);ctx.lineTo(x-1,y+3);ctx.lineTo(x+4,y-4);ctx.stroke();}
      } else {for(const signal of network.signals){const [x,y]=project(signal.position);ctx.fillStyle='#ffffff';ctx.beginPath();ctx.arc(x,y,8,0,Math.PI*2);ctx.fill();ctx.fillStyle='#858585';ctx.beginPath();ctx.arc(x,y,4.5,0,Math.PI*2);ctx.fill();}}
      if(interactive){
      // A small overview keeps the whole journey legible while following locally.
      const mw=width<450?104:148,mh=width<450?68:96,mx=width-mw-14,my=height/2-mh/2;
      ctx.fillStyle='#fffffff2';ctx.strokeStyle='#c6c6c6';ctx.lineWidth=1;roundRect(ctx,mx,my,mw,mh,5);ctx.fill();ctx.stroke();
      ctx.save();ctx.beginPath();ctx.rect(mx+1,my+1,mw-2,mh-2);ctx.clip();
      const miniScale=Math.min((mw-16)/(maxX-minX),(mh-16)/(maxY-minY));
      const mini=(p:number[])=>[mx+mw/2+(p[0]-(minX+maxX)/2)*miniScale,my+mh/2+((minY+maxY)/2-p[1])*miniScale];
      ctx.strokeStyle='#9a9a9a';ctx.lineWidth=2;
      for(const shape of network.route){ctx.beginPath();shape.forEach((p,i)=>{const [x,y]=mini(p);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});ctx.stroke();}
      for(const [p,r] of [[network.origin,2],[network.hospital,3],[position,4]] as [number[],number][]){const [x,y]=mini(p);ctx.fillStyle='#202020';ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
      if(cam.mode!=='overview'){const corners=[[(width/2-offsetX)/scale+minX,(maxY-(height/2-offsetY)/scale)]];const [x,y]=mini(corners[0]);ctx.strokeStyle='#202020';ctx.lineWidth=1;ctx.strokeRect(x-width/scale*miniScale/2,y-height/scale*miniScale/2,width/scale*miniScale,height/scale*miniScale);}
      ctx.restore();
      const scaleY=width<450?height-145:height-210;
      ctx.textAlign='left';ctx.fillStyle='#555';ctx.font='600 10px Arial';const metres=scale>.4?100:500;ctx.fillText(`${metres} m`,16,scaleY);ctx.strokeStyle='#555';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(16,scaleY+7);ctx.lineTo(16+metres*scale,scaleY+7);ctx.stroke();
      }
      raf=requestAnimationFrame(draw);
    };
    raf=requestAnimationFrame(draw);
    return ()=>{cancelAnimationFrame(raf);observer.disconnect();};
  },[network,side,buffers,playhead,interactive]);
  return <>{interactive&&<div className="camera-tools" aria-label={`${side} map camera`}><button aria-pressed={mode==='follow'} onClick={()=>choose('follow')}>Follow ambulance</button><button aria-pressed={mode==='overview'} onClick={()=>choose('overview')}>Entire route</button><button aria-label={`Zoom in ${side} map`} onClick={()=>changeZoom(1.4)}>+</button><button aria-label={`Zoom out ${side} map`} onClick={()=>changeZoom(1/1.4)}>-</button></div>}<canvas
    onPointerDown={e=>{if(!interactive)return;drag.current={x:e.clientX,y:e.clientY};e.currentTarget.setPointerCapture(e.pointerId);}}
    onPointerMove={e=>{if(!drag.current)return;const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y;if(Math.abs(dx)+Math.abs(dy)<2)return;const cam=camera.current;if(cam.mode==='follow'){const position=frameAt(buffers.current[side],playhead.current)[0]?.ambulance.position??network.origin;const [minX,minY,maxX,maxY]=network.bounds;const rect=e.currentTarget.getBoundingClientRect();const previousScale=Math.min(rect.width,rect.height)/650*cam.zoom;const base=Math.min((rect.width-44)/(maxX-minX),(rect.height-70)/(maxY-minY));cam.zoom=previousScale/base;cam.panX=((minX+maxX)/2-position[0])*previousScale;cam.panY=(position[1]-(minY+maxY)/2)*previousScale;}cam.mode='free';setMode('free');cam.panX+=dx;cam.panY+=dy;drag.current={x:e.clientX,y:e.clientY};}}
    onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}
 ref={canvas} className="traffic-canvas" aria-label={`${side==='zelvo'?'With':'Without'} ZELVO, vehicle map of ${network.location}`} role="img"/></>;
}
