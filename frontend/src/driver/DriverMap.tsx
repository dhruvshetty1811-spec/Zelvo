import { useEffect, useRef } from 'react';
import type { MutableRefObject } from 'react';
import network from './network.json';

const points=network.route.flat() as number[][];
const lengths=[0];
for(let i=1;i<points.length;i++)lengths.push(lengths[i-1]+Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));
const total=lengths[lengths.length-1];
export const ROUTE_METRES=network.route_length_m;
export const JUNCTION_PROGRESS=network.signals.map(signal=>{
  let nearest=0,best=Infinity;
  points.forEach((p,i)=>{const d=Math.hypot(p[0]-signal.position[0],p[1]-signal.position[1]);if(d<best){nearest=i;best=d;}});
  return lengths[nearest]/total;
}).sort((a,b)=>a-b);

function routePosition(progress:number){
  const distance=Math.max(0,Math.min(1,progress))*total;
  let i=1;while(i<lengths.length-1&&lengths[i]<distance)i++;
  const fraction=(distance-lengths[i-1])/Math.max(.001,lengths[i]-lengths[i-1]);
  const a=points[i-1],b=points[i];
  return {position:[a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction],angle:Math.atan2(-(b[1]-a[1]),b[0]-a[0])+Math.PI/2};
}

export function DriverMap({progress,following,navigation,arrived,revision}:{progress:MutableRefObject<number>;following:boolean;navigation:boolean;arrived:boolean;revision:number}){
  const canvas=useRef<HTMLCanvasElement>(null);
  useEffect(()=>{
    const el=canvas.current!;const ctx=el.getContext('2d')!;
    let width=0,height=0,raf=0;
    const resize=new ResizeObserver(()=>{width=el.clientWidth;height=el.clientHeight;const dpr=Math.min(2,devicePixelRatio||1);el.width=Math.round(width*dpr);el.height=Math.round(height*dpr);});resize.observe(el);
    const roads=network.roads.map(road=>{
      const path=new Path2D();road.shape.forEach(([x,y],i)=>i?path.lineTo(x,-y):path.moveTo(x,-y));
      return {...road,path,minX:Math.min(...road.shape.map(p=>p[0])),maxX:Math.max(...road.shape.map(p=>p[0])),minY:Math.min(...road.shape.map(p=>p[1])),maxY:Math.max(...road.shape.map(p=>p[1]))};
    });
    const route=new Path2D();points.forEach(([x,y],i)=>i?route.lineTo(x,-y):route.moveTo(x,-y));
    const draw=()=>{
      if(width&&height){
        const ratio=el.width/width;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.fillStyle='#eaeaea';ctx.fillRect(0,0,width,height);
        const current=routePosition(progress.current);
        const [minX,minY,maxX,maxY]=network.bounds;
        const sheet=el.parentElement?.querySelector<HTMLElement>('.driver-sheet');
        const top=navigation?240:125,bottom=Math.max(top+100,(sheet?.offsetTop??height*.6)-20);
        const scale=following?Math.min(width,height)/650:Math.min((width-64)/(maxX-minX),(bottom-top)/(maxY-minY));
        const center=following?current.position:[(minX+maxX)/2,(minY+maxY)/2];
        const ox=width/2-center[0]*scale,oy=(top+bottom)/2+center[1]*scale;
        const project=(p:number[])=>[p[0]*scale+ox,-p[1]*scale+oy];
        const visible=roads.filter(r=>r.maxX*scale+ox>-40&&r.minX*scale+ox<width+40&&-r.minY*scale+oy>-40&&-r.maxY*scale+oy<height+40);
        ctx.save();ctx.translate(ox,oy);ctx.scale(scale,scale);ctx.lineCap='round';ctx.lineJoin='round';
        for(const r of visible){ctx.strokeStyle='#d7d7d7';ctx.lineWidth=(r.lanes>2?12:7)/scale;ctx.stroke(r.path);ctx.strokeStyle='#fff';ctx.lineWidth=(r.lanes>2?10:5)/scale;ctx.stroke(r.path);}
        ctx.strokeStyle='#fff';ctx.lineWidth=9/scale;ctx.stroke(route);ctx.strokeStyle='#222';ctx.lineWidth=4.5/scale;ctx.stroke(route);ctx.restore();
        let labels=0;const names=new Set<string>();
        for(const r of visible){
          if(!r.name||names.has(r.name)||labels>=5)continue;
          const p=project(r.shape[Math.floor(r.shape.length/2)]);
          if(p[0]<40||p[0]>width-50||p[1]<180||p[1]>height-330)continue;
          names.add(r.name);labels++;ctx.fillStyle='#8a8a8a';ctx.font='10px Arial';ctx.textAlign='center';ctx.fillText(r.name.length>25?r.name.slice(0,23)+'…':r.name,p[0],p[1]-12);
        }
        const hospital=project(points[points.length-1]);
        ctx.fillStyle='#171717';ctx.beginPath();ctx.arc(hospital[0],hospital[1],10,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(hospital[0]-4,hospital[1]);ctx.lineTo(hospital[0]+4,hospital[1]);ctx.moveTo(hospital[0],hospital[1]-4);ctx.lineTo(hospital[0],hospital[1]+4);ctx.stroke();
        if(!following){ctx.font='600 10px Arial';ctx.textAlign='center';ctx.fillStyle='#333';ctx.fillText('Hospital',hospital[0],hospital[1]+23);}
        if(!arrived){
          const [x,y]=project(current.position);ctx.fillStyle='#17171710';ctx.beginPath();ctx.arc(x,y,27,0,Math.PI*2);ctx.fill();ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(x,y,18,0,Math.PI*2);ctx.fill();ctx.save();ctx.translate(x,y);ctx.rotate(current.angle);ctx.fillStyle='#171717';ctx.beginPath();ctx.moveTo(0,-12);ctx.lineTo(9,10);ctx.lineTo(0,6);ctx.lineTo(-9,10);ctx.closePath();ctx.fill();ctx.restore();
        }
      }
      raf=requestAnimationFrame(draw);
    };raf=requestAnimationFrame(draw);return()=>{cancelAnimationFrame(raf);resize.disconnect();};
  },[progress,following,navigation,arrived,revision]);
  return <canvas ref={canvas} className="driver-map" role="img" aria-label="Illustrative hospital route on Bengaluru road geometry, with simulated ambulance location"/>;
}
