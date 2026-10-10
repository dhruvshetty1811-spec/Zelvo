import { useEffect, useState } from 'react';
import { ArrowUpRight, ChevronLeft, Menu } from 'lucide-react';
import { Landing } from './Landing';
import { Demo } from './Demo';
import type { Network } from './types';
import mapData from './data/network.json';

const network=mapData as Network;
function Logo({onClick}:{onClick:()=>void}) {return <button className="brand" onClick={onClick} aria-label="ZELVO home"><svg viewBox="0 0 30 30" aria-hidden="true"><path d="M5 7h21L8 23h18M4 15h21" fill="none" stroke="currentColor" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round"/></svg><span>zelvo</span></button>;}
function App() {
  const [demo,setDemo]=useState(location.hash==='#demo');
  const [mobileMenu,setMobileMenu]=useState(false);
  const [immersive,setImmersive]=useState(false);
  useEffect(()=>{const change=()=>{setDemo(location.hash==='#demo');setMobileMenu(false);};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
  const navigate=(target:string)=>{location.hash=target;setDemo(target==='demo');setMobileMenu(false);if(target==='demo'||target==='')window.scrollTo(0,0);};
  return <><a className="skip-link" href="#main">Skip to content</a><header className="site-header" hidden={immersive}><div className="nav-shell"><Logo onClick={()=>navigate('')}/><nav aria-label="Main navigation" className={mobileMenu?'nav-links open':'nav-links'}>{demo?<button className="nav-back" onClick={()=>navigate('')}><ChevronLeft size={15}/>Back to the overview</button>:<><a href="#how-it-works">How it works</a><a href="#evidence">The evidence</a></>}</nav><button className="button nav-cta" onClick={()=>navigate('demo')}>Launch demo <ArrowUpRight size={16}/></button><button className="mobile-toggle" aria-label="Toggle navigation" aria-expanded={mobileMenu} onClick={()=>setMobileMenu(!mobileMenu)}><Menu size={22}/></button></div></header>{demo?<Demo network={network} onImmersiveChange={setImmersive} onHome={()=>{navigate('');requestAnimationFrame(()=>document.querySelector<HTMLHeadingElement>('.opening h1')?.focus({preventScroll:true}));}}/>:<Landing openDemo={()=>navigate('demo')} network={network}/>}<footer className="site-footer" hidden={immersive}><div className="page-width footer-row"><Logo onClick={()=>navigate('')}/><p>A clear path. Before the siren arrives.</p><span>Bengaluru, India</span><a className="footer-driver-link" href="/driver.html">Mobile app</a><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">Map data © OpenStreetMap contributors <ArrowUpRight size={12}/></a></div></footer></>;
}

export default App;
