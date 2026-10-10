import { useEffect, useRef, useState } from 'react';
import { Ambulance, ArrowLeft, ArrowRight, ArrowUp, ArrowUpRight, BatteryFull, Check, ChevronRight, Clock3, Cross, Flag, LocateFixed, MapPin, Navigation, Pause, Play, RotateCcw, Search, ShieldCheck, Signal, Wifi, X } from 'lucide-react';
import { DriverMap, JUNCTION_PROGRESS, ROUTE_METRES } from './DriverMap';

type Screen='choose'|'preview'|'trip'|'arrived';
const hospitals=[{name:'Victoria Hospital',detail:'Hospital destination'},{name:'Central Hospital',detail:'Demo hospital destination'},{name:'City Medical Centre',detail:'Demo hospital destination'}];
const DURATION=480;
function Mark(){return <svg viewBox="0 0 30 30" aria-hidden="true"><path d="M5 7h21L8 23h18M4 15h21" fill="none" stroke="currentColor" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round"/></svg>;}
const minutes=(s:number)=>Math.max(1,Math.ceil(s/60));

export function DriverApp(){
  const [screen,setScreen]=useState<Screen>('choose');
  const [query,setQuery]=useState('');const [destination,setDestination]=useState('');
  const [elapsed,setElapsed]=useState(0);const [paused,setPaused]=useState(false);const [confirmEnd,setConfirmEnd]=useState(false);
  const [speed,setSpeed]=useState(8);const [overview,setOverview]=useState(false);const [revision,setRevision]=useState(0);
  const progress=useRef(0),elapsedRef=useRef(0),search=useRef<HTMLInputElement>(null),heading=useRef<HTMLHeadingElement>(null),dialog=useRef<HTMLDivElement>(null),endButton=useRef<HTMLButtonElement>(null);
  const active=screen==='trip';const matches=hospitals.filter(h=>h.name.toLowerCase().includes(query.toLowerCase().trim()));
  const distance=Math.max(0,ROUTE_METRES*(1-elapsed/DURATION));
  const nextJunction=JUNCTION_PROGRESS.find(p=>p>elapsed/DURATION+15/ROUTE_METRES);
  const cueDistance=nextJunction==null?distance:(nextJunction-elapsed/DURATION)*ROUTE_METRES;
  useEffect(()=>{
    if(!active||paused||confirmEnd)return;
    let raf=0,last=performance.now();
    const tick=(now:number)=>{const dt=Math.min(.25,(now-last)/1000);last=now;elapsedRef.current=Math.min(DURATION,elapsedRef.current+dt*speed);progress.current=elapsedRef.current/DURATION;setElapsed(Math.floor(elapsedRef.current));if(elapsedRef.current>=DURATION){setScreen('arrived');return;}raf=requestAnimationFrame(tick);};
    raf=requestAnimationFrame(tick);return()=>cancelAnimationFrame(raf);
  },[active,paused,speed,confirmEnd]);
  useEffect(()=>{if(screen!=='choose')heading.current?.focus({preventScroll:true});},[screen]);
  useEffect(()=>{
    if(!confirmEnd)return;
    const box=dialog.current!;const buttons=Array.from(box.querySelectorAll<HTMLButtonElement>('button'));buttons[0]?.focus();
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setConfirmEnd(false);endButton.current?.focus();}if(e.key==='Tab'){const first=buttons[0],last=buttons[buttons.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};box.addEventListener('keydown',key);return()=>box.removeEventListener('keydown',key);
  },[confirmEnd]);
  const reset=()=>{setScreen('choose');setQuery('');setDestination('');setElapsed(0);elapsedRef.current=0;progress.current=0;setPaused(false);setConfirmEnd(false);setOverview(false);setRevision(v=>v+1);requestAnimationFrame(()=>search.current?.focus({preventScroll:true}));};
  const select=(name:string)=>{setDestination(name.trim().slice(0,80));setScreen('preview');setQuery('');};
  const start=()=>{elapsedRef.current=0;progress.current=0;setElapsed(0);setPaused(false);setOverview(false);setScreen('trip');};
  const closeDialog=()=>{setConfirmEnd(false);requestAnimationFrame(()=>endButton.current?.focus());};

  return <main className="driver-canvas">
    <header className="driver-page-header"><a href="/" className="driver-page-brand" aria-label="Back to ZELVO"><Mark/><span>zelvo</span></a><span>Driver app <i/> Interactive preview</span><a href="/" className="driver-back"><ArrowLeft size={14}/>Back to ZELVO</a></header>
    <section className="driver-showcase" aria-label="Interactive iPhone driver app preview">
      <div className="driver-device"><span className="device-button silent"/><span className="device-button volume-up"/><span className="device-button volume-down"/><span className="device-button power"/>
        <div className="driver-screen">
          <DriverMap progress={progress} following={screen==='choose'||active&&!overview} navigation={active} arrived={screen==='arrived'} revision={revision}/>
          <div className="driver-map-scrim" aria-hidden="true"/>
          <div className="phone-status" aria-hidden="true"><span>9:41</span><div className="dynamic-island"/><div><Signal size={15} strokeWidth={2.8}/><Wifi size={15} strokeWidth={2.8}/><BatteryFull size={22}/></div></div>
          {(screen==='choose'||screen==='preview')&&<header className="driver-app-header"><div className="driver-app-brand"><Mark/><span>zelvo</span><span>Driver</span></div><span className="driver-avatar" aria-label="Ambulance driver"><Ambulance size={20}/></span></header>}
          {screen==='choose'&&<div className="driver-location"><span className="location-dot"/><div><span>Current location</span><strong>Bengaluru</strong></div><LocateFixed size={17}/></div>}
          {screen==='preview'&&<button className="driver-map-back" onClick={()=>{setScreen('choose');setTimeout(()=>search.current?.focus(),0);}} aria-label="Change hospital destination"><ArrowLeft size={20}/></button>}
          {active&&<><div className="driver-maneuver"><span><ArrowUp size={38} strokeWidth={2.5}/></span><div><span>{distance>250?'Continue ahead':'Approaching destination'}</span><h1 ref={heading} tabIndex={-1}>{distance>250?`${Math.max(10,Math.round(cueDistance/10)*10)} m`:'Hospital entrance'}</h1><p>{distance>250?(nextJunction==null?'To hospital entrance':'To the next junction'):destination}</p></div></div><div className="driver-priority"><ShieldCheck size={15}/><span>{paused?'Trip paused':'Simulated priority active'}</span><span className="priority-dot"/></div><button className="driver-recenter" aria-label={overview?'Follow ambulance':'Show entire route'} onClick={()=>setOverview(v=>!v)}>{overview?<Navigation size={21}/>:<LocateFixed size={21}/>}</button></>}

          {screen==='choose'&&<section className="driver-sheet choose-sheet" aria-labelledby="driver-choose-title"><div className="sheet-handle"/><h1 id="driver-choose-title">Where are we headed?</h1><p className="driver-sheet-subtitle">Choose the hospital for this trip.</p><form onSubmit={e=>{e.preventDefault();if(query.trim())select(query);}}><label htmlFor="hospital-search" className="driver-sr-only">Hospital destination</label><div className="driver-search"><Search size={20}/><input ref={search} id="hospital-search" placeholder="Search for a hospital" value={query} maxLength={80} onChange={e=>setQuery(e.target.value)} autoComplete="off"/>{query&&<button type="button" aria-label="Clear hospital search" onClick={()=>{setQuery('');search.current?.focus();}}><X size={17}/></button>}</div></form><div className="driver-list-heading">{query?'Search results':'Suggested hospitals'}<span>Demo destinations</span></div><div className="driver-hospital-list">{matches.map(h=><button key={h.name} onClick={()=>select(h.name)}><span className="hospital-icon"><Cross size={18}/></span><span><strong>{h.name}</strong><small>{h.detail}</small></span><ChevronRight size={17}/></button>)}{query.trim()&&!hospitals.some(h=>h.name.toLowerCase()===query.trim().toLowerCase())&&<button onClick={()=>select(query)} className="custom-hospital"><span className="hospital-icon"><MapPin size={18}/></span><span><strong>Use “{query.trim()}”</strong><small>Custom demo destination</small></span><ArrowUpRight size={17}/></button>}</div><p className="driver-private"><ShieldCheck size={13}/>Location stays in this preview.</p></section>}

          {screen==='preview'&&<section className="driver-sheet preview-sheet" aria-labelledby="driver-preview-title"><div className="sheet-handle"/><div className="driver-preview-label"><span className="hospital-icon"><Cross size={19}/></span><div><span>Your destination</span><h1 ref={heading} tabIndex={-1} id="driver-preview-title">{destination}</h1></div><button className="driver-icon-button" aria-label="Change hospital destination" onClick={()=>{setScreen('choose');setTimeout(()=>search.current?.focus(),0);}}><X size={19}/></button></div><div className="driver-route-stats"><div><strong>8 <span>min</span></strong><span>Estimated trip</span></div><div><strong>{(ROUTE_METRES/1000).toFixed(1)} <span>km</span></strong><span>Route distance</span></div><span className="driver-route-tag">Demo route</span></div><div className="driver-ready-note"><ShieldCheck size={19}/><div><strong>A clearer way ahead.</strong><p>Preview how ZELVO prepares your route.</p></div></div><button className="driver-primary" onClick={start}><Navigation size={18} fill="currentColor"/>Start trip<ArrowRight size={19}/></button><p className="driver-demo-note">Simulated location, route and signal priority.</p></section>}

          {active&&<section className="driver-sheet trip-sheet" aria-label="Active trip controls"><div className="sheet-handle"/><div className="driver-trip-stats"><div><strong>{minutes(DURATION-elapsed)} <span>min</span></strong><span>Remaining</span></div><div><strong>{(distance/1000).toFixed(1)} <span>km</span></strong><span>To destination</span></div><div><strong>9:49</strong><span>Demo arrival</span></div></div><div className="driver-trip-progress" role="progressbar" aria-label="Trip progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(100*elapsed/DURATION)}><span style={{width:`${elapsed/DURATION*100}%`}}/></div><div className="driver-trip-destination"><span className="hospital-icon"><Cross size={17}/></span><div><span>Hospital destination</span><strong>{destination}</strong></div><Flag size={17}/></div><div className="driver-trip-actions"><button className="driver-pause" onClick={()=>setPaused(v=>!v)}>{paused?<Play size={18}/>:<Pause size={18}/>}<span>{paused?'Resume':'Pause'}</span></button><button ref={endButton} className="driver-end" onClick={()=>setConfirmEnd(true)}>End trip<X size={16}/></button></div></section>}

          {screen==='arrived'&&<section className="driver-arrival" aria-labelledby="arrival-title"><div className="arrival-symbol"><Check size={38}/></div><span>Trip complete</span><h1 ref={heading} tabIndex={-1} id="arrival-title">You’ve arrived.</h1><p>{destination}</p><div className="arrival-trip"><div><Clock3 size={18}/><strong>8 min</strong><span>Demo trip time</span></div><div><Navigation size={18}/><strong>{(ROUTE_METRES/1000).toFixed(1)} km</strong><span>Route completed</span></div></div><p className="arrival-note">This preview is complete. No real signal requests were sent.</p><button className="driver-primary" onClick={reset}>Start a new trip<ArrowRight size={19}/></button></section>}

          {confirmEnd&&<div className="driver-dialog-backdrop"><div ref={dialog} className="driver-dialog" role="dialog" aria-modal="true" aria-labelledby="end-trip-title"><span className="dialog-icon"><Flag size={23}/></span><h2 id="end-trip-title">End this trip?</h2><p>You can choose a new destination after ending this trip.</p><button className="driver-primary" onClick={closeDialog}>Continue trip</button><button className="dialog-end" onClick={reset}>End trip</button></div></div>}
          <div className="home-indicator" aria-hidden="true"/>
        </div>
      </div>
      <div className="driver-preview-controls"><span>Try the driver experience.</span><div><label htmlFor="demo-speed">Demo speed</label><select id="demo-speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value={1}>1×</option><option value={8}>8×</option><option value={32}>32×</option></select><button onClick={reset} aria-label="Restart driver preview"><RotateCcw size={15}/></button></div></div>
      <p className="driver-disclosure">Interactive prototype. All destinations share an illustrative route.<br/>Location and signal priority are simulated. <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">Map data © OpenStreetMap.</a></p>
    </section>
  </main>;
}
