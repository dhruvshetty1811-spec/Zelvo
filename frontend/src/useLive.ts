import { useCallback, useEffect, useRef, useState } from 'react';
import type { Frame, Receipt, Settings, Side } from './types';

export type Buffers = Record<Side, Frame[]>;
export function frameAt(frames: Frame[], time: number): [Frame | undefined, Frame | undefined, number] {
  if (!frames.length || time < frames[0].time_s) return [undefined, undefined, 0];
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const mid = Math.ceil((lo+hi)/2); if (frames[mid].time_s <= time) lo=mid; else hi=mid-1; }
  const a=frames[lo], b=frames[Math.min(lo+1,frames.length-1)];
  return [a,b,b.time_s===a.time_s?0:Math.min(1,Math.max(0,(time-a.time_s)/(b.time_s-a.time_s)))];
}
export function useLive() {
  const buffers = useRef<Buffers>({baseline:[],zelvo:[]});
  const playhead = useRef(60);
  const playingRef = useRef(true), speedRef=useRef(4), generation=useRef(0);
  const socket = useRef<WebSocket | null>(null), heartbeat=useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const terminalRef=useRef(false), sessionRef=useRef<string | null>(null);
  const [status,setStatus]=useState('idle'), [error,setError]=useState(''), [session,setSession]=useState<string | null>(null);
  const [receipt,setReceipt]=useState<Receipt | null>(null),[clock,setClock]=useState(60),[buffering,setBuffering]=useState(false);
  const [playing,setPlaying]=useState(true),[speed,setSpeed]=useState(4);
  const [views,setViews]=useState<Partial<Record<Side,Frame>>>({});

  useEffect(()=>{
    let raf=0,previous=0,lastUI=0;
    const tick=(now:number)=>{
      const dt=previous?Math.min(.1,(now-previous)/1000):0; previous=now;
      const a=buffers.current.baseline, b=buffers.current.zelvo;
      const la=a.at(-1),lb=b.at(-1);
      let waiting=false;
      if (la && lb && playingRef.current) {
        const end=la.ambulance.arrived&&lb.ambulance.arrived?Math.max(la.time_s,lb.time_s):Math.min(la.ambulance.arrived?Infinity:la.time_s,lb.ambulance.arrived?Infinity:lb.time_s);
        const target=playhead.current+dt*speedRef.current;
        // A 0.4s interpolation buffer absorbs packet jitter; never extrapolate.
        const limit=Math.max(a[0].time_s,b[0].time_s, end-(la.ambulance.arrived&&lb.ambulance.arrived?0:.4));
        playhead.current=Math.min(target,limit);
        waiting=target>limit && !(la.ambulance.arrived&&lb.ambulance.arrived&&playhead.current>=end);
      } else if (sessionRef.current && !terminalRef.current) waiting=true;
      if(now-lastUI>100) {
        setClock(playhead.current);setBuffering(waiting);
        setViews({baseline:frameAt(a,playhead.current)[0],zelvo:frameAt(b,playhead.current)[0]}); lastUI=now;
      }
      raf=requestAnimationFrame(tick);
    };
    raf=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(raf);
  },[]);

  const start=useCallback(async(settings:Settings)=>{
    const token=++generation.current;
    socket.current?.close(); clearInterval(heartbeat.current);
    terminalRef.current=false;buffers.current={baseline:[],zelvo:[]};
    sessionRef.current=null;setSession(null);
    playhead.current=settings.dispatch_s;setClock(settings.dispatch_s);setViews({});
    setError('');setReceipt(null);setStatus('starting');setPlaying(true);playingRef.current=true;
    try {
      const response=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
      const body=response.headers.get('content-type')?.includes('application/json')?await response.json():{detail:'The local engine could not start this comparison. Check the server log, then try again.'};
      if(!response.ok) throw new Error(typeof body.detail==='string'?body.detail:'Check the scenario settings and try again.');
      if(token!==generation.current) { await fetch(`/api/sessions/${body.id}`,{method:'DELETE'}); return; }
      sessionRef.current=body.id;setSession(body.id);setStatus('running');
      const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/sessions/${body.id}/stream`);
      socket.current=ws;
      ws.onmessage=(event)=>{
        if(token!==generation.current)return;
        const message=JSON.parse(event.data);
        if(message.type==='frames') buffers.current[message.side as Side].push(...message.frames);
        if(message.type==='finished') {terminalRef.current=true;setReceipt(message);setStatus(message.status);clearInterval(heartbeat.current); if(Object.keys(message.errors).length)setError(Object.values(message.errors).join(' '));}
      };
      ws.onopen=()=>{heartbeat.current=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send('ping');},5000);};
      ws.onerror=()=>{if(token===generation.current)setError('The live connection was interrupted. Stop this comparison, then start a new one.');};
      ws.onclose=()=>{clearInterval(heartbeat.current);if(token===generation.current&&!terminalRef.current){setStatus('disconnected');setError('The live connection closed. Stop this comparison before trying again. Its recorded data stays in the run folder.');}};
    } catch(e) {if(token===generation.current){terminalRef.current=true;setStatus('failed');setError(e instanceof TypeError?'Could not reach the local engine. Restart the ZELVO server, refresh this page, and try again.':e instanceof Error?e.message:'Could not start the comparison. Start the local ZELVO server and try again.');}}
  },[]);
  const cancel=useCallback(async()=>{
    if(!sessionRef.current){++generation.current;terminalRef.current=true;setStatus('cancelled');return;}
    setStatus('stopping');
    try {
      const response=await fetch(`/api/sessions/${sessionRef.current}`,{method:'DELETE'});
      if(!response.ok)throw new Error('Could not reach the server to stop this comparison.');
      if(socket.current?.readyState!==WebSocket.OPEN){terminalRef.current=true;setStatus('cancelled');}
    }catch(e){setError(e instanceof Error?e.message:'Stop failed. Try again.');setStatus('disconnected');}
  },[]);
  const toggle=()=>{playingRef.current=!playingRef.current;setPlaying(playingRef.current);};
  const changeSpeed=(value:number)=>{speedRef.current=value;setSpeed(value);};
  const replay=()=>{const first=buffers.current.baseline[0];if(first){playhead.current=first.time_s;playingRef.current=true;setPlaying(true);}};
  useEffect(()=>()=>{++generation.current;clearInterval(heartbeat.current);socket.current?.close();if(sessionRef.current&&!terminalRef.current)void fetch(`/api/sessions/${sessionRef.current}`,{method:'DELETE',keepalive:true});},[]);
  return {buffers,playhead,status,error,session,receipt,clock,buffering,playing,speed,views,start,cancel,toggle,changeSpeed,replay};
}
