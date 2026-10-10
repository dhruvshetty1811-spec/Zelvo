import { useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, RotateCcw } from 'lucide-react';
import { TrafficMap } from './TrafficMap';
import { frameAt } from './useLive';
import type { Buffers } from './useLive';
import type { Frame, Network } from './types';

export function HeroMap({network}:{network:Network}) {
  const buffers=useRef<Buffers>({baseline:[],zelvo:[]}),playhead=useRef(60),visible=useRef(true),element=useRef<HTMLDivElement>(null);
  const [playing,setPlaying]=useState(()=>!window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [ready,setReady]=useState(false),[error,setError]=useState(false),[attempt,setAttempt]=useState(0);
  const [elapsed,setElapsed]=useState(0),[arrived,setArrived]=useState(false);
  const previewNetwork=useMemo(()=>{
    const points=network.route.flat(),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    return {...network,bounds:[Math.min(...xs)-150,Math.min(...ys)-100,Math.max(...xs)+150,Math.max(...ys)+100]};
  },[network]);
  useEffect(()=>{
    const controller=new AbortController();setError(false);
    Promise.resolve().then(()=>{if(controller.signal.aborted)return null;return fetch('/corridor-preview.json',{signal:controller.signal});}).then(response=>{if(!response)return null;if(!response.ok)throw Error();return response.json();}).then((data:{frames:Frame[]}|null)=>{if(!data||controller.signal.aborted)return;if(!data.frames.length)throw Error();buffers.current.zelvo=data.frames;playhead.current=data.frames[0].time_s;setReady(true);}).catch(()=>{if(!controller.signal.aborted)setError(true);});
    return()=>controller.abort();
  },[attempt]);
  useEffect(()=>{const observer=new IntersectionObserver(([entry])=>{visible.current=entry.isIntersecting;});if(element.current)observer.observe(element.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{const media=window.matchMedia('(prefers-reduced-motion: reduce)');const change=()=>{if(media.matches)setPlaying(false);};media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
  useEffect(()=>{
    let raf=0,previous=0,lastUI=0;
    const tick=(now:number)=>{
      const frames=buffers.current.zelvo,first=frames[0],last=frames.at(-1);
      if(first&&last&&playing&&visible.current){playhead.current+=Math.min(.1,previous?(now-previous)/1000:0)*3;if(playhead.current>last.time_s+2)playhead.current=first.time_s;}
      if(first&&visible.current&&now-lastUI>150){setElapsed(Math.min(playhead.current,frames.at(-1)!.time_s)-first.time_s);setArrived(!!frameAt(frames,playhead.current)[0]?.ambulance.arrived);lastUI=now;}
      previous=now;raf=requestAnimationFrame(tick);
    };raf=requestAnimationFrame(tick);return()=>cancelAnimationFrame(raf);
  },[playing]);
  const restart=()=>{playhead.current=buffers.current.zelvo[0]?.time_s??60;setElapsed(0);setArrived(false);setPlaying(true);};
  return <div className="hero-map preview-map" ref={element} aria-label="Animated recorded simulation of the Victoria Hospital ambulance corridor">
    <TrafficMap network={previewNetwork} side="zelvo" buffers={buffers} playhead={playhead} interactive={false}/>
    <div className="map-heading"><span className="map-key"><i/>The road ahead, in motion</span><span>Victoria Hospital / Bengaluru</span></div>
    <div className="preview-footer"><div className="preview-status"><span className={`preview-dot ${playing&&ready?'playing':''}`}/><div><strong>{error?'Replay unavailable':!ready?'Loading corridor replay':arrived?'Ambulance arrived':'Ambulance corridor replay'}</strong><span>Recorded SUMO simulation{ready?' / 3× playback':''}</span></div></div><div className="preview-controls">{error?<button onClick={()=>setAttempt(attempt+1)}>Retry replay</button>:<><span className="preview-clock">{Math.floor(elapsed/60)}:{Math.floor(elapsed%60).toString().padStart(2,'0')}</span><button disabled={!ready} aria-label={playing?'Pause corridor preview':'Play corridor preview'} onClick={()=>setPlaying(!playing)}>{playing?<Pause size={17}/>:<Play size={17}/>}</button><button disabled={!ready} aria-label="Restart corridor preview" onClick={restart}><RotateCcw size={17}/></button></>}</div></div>
  </div>;
}
