// Public OSM extract, no API key. Run with node --use-system-ca.
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const directory = 'scenarios/bengaluru';
const bbox = [12.952,77.565,12.995,77.619]; // south,west,north,east
const query = `[out:xml][timeout:180];(way[highway](${bbox.join(',')});relation[type=restriction](${bbox.join(',')}););(._;>;);out body;`;
await mkdir(directory, {recursive:true});
let response, endpoint;
for (const url of ['https://overpass-api.de/api/interpreter?data='+encodeURIComponent(query), 'https://api.openstreetmap.org/api/0.6/map?bbox=77.565,12.952,77.619,12.995']) {
  try {
    response = await fetch(url, {signal:AbortSignal.timeout(240000)});
    console.log(`OSM HTTP ${response.status}`);
    if (response.ok) { endpoint = url; break; }
  } catch (error) { console.log(error.message); }
}
let data;
if (!endpoint) {
  // OSM map API caps node count per request. Fetch small tiles, preserving originals.
  const elements = new Map();
  const urls = [];
  for (let row=0;row<3;row++) for(let col=0;col<3;col++) {
    const south=bbox[0]+(bbox[2]-bbox[0])*row/3, north=bbox[0]+(bbox[2]-bbox[0])*(row+1)/3;
    const west=bbox[1]+(bbox[3]-bbox[1])*col/3, east=bbox[1]+(bbox[3]-bbox[1])*(col+1)/3;
    const url=`https://api.openstreetmap.org/api/0.6/map?bbox=${west},${south},${east},${north}`;
    const tile=await fetch(url,{signal:AbortSignal.timeout(120000)});
    if(!tile.ok) throw new Error(`OSM tile ${row},${col}: ${tile.status} ${await tile.text()}`);
    const xml=await tile.text();
    await writeFile(`${directory}/tile-${row}-${col}.osm.xml`,xml);
    for(const match of xml.matchAll(/<(node|way|relation)\b[^>]*\bid="(\d+)"[^>]*(?:\/>|>[\s\S]*?<\/\1>)/g)) elements.set(`${match[1]}-${match[2]}`,match[0]);
    urls.push(url);console.log(`tile ${row},${col} ${xml.length} bytes`);
  }
  endpoint=urls;
  data=Buffer.from('<?xml version="1.0" encoding="UTF-8"?><osm version="0.6" generator="ZELVO tile merge">\n'+[...elements.values()].join('\n')+'\n</osm>');
} else data = Buffer.from(await response.arrayBuffer());
if (!data.toString().includes('<osm') || data.toString().includes('<remark>')) throw new Error('Incomplete OSM response');
await writeFile(`${directory}/district.osm.xml`, data);
await writeFile(`${directory}/source.json`, JSON.stringify({endpoint,query,bbox,downloaded_at:new Date().toISOString(),sha256:createHash('sha256').update(data).digest('hex'),attribution:'© OpenStreetMap contributors',license:'ODbL 1.0',license_url:'https://www.openstreetmap.org/copyright'},null,2)+'\n');
console.log(JSON.stringify({bytes:data.length,directory}));
