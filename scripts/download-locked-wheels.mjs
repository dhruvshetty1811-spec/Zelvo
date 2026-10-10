// Download locked wheels through a mirror if the primary CDN is unreachable.
// Every byte is verified against the SHA-256 in uv.lock.
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
await mkdir('.tools/wheels',{recursive:true});
const lock=await readFile('uv.lock','utf8');
const names=process.argv.slice(2).length?process.argv.slice(2):['numpy','scipy','scikit-learn','joblib','threadpoolctl','pyproj','certifi'];
for(const block of lock.split('[[package]]')) {
  const name=block.match(/\nname = "([^"]+)"/u)?.[1];
  if(!names.includes(name))continue;
  const wheels=[...block.matchAll(/\{ url = "([^"]+\.whl)", hash = "sha256:([^"]+)"/gu)];
  const wheel=wheels.find(w=>/cp312-cp312-win_amd64\.whl$/u.test(w[1])) || wheels.find(w=>/(py3|py2.py3)-none-(any|win_amd64)\.whl$/u.test(w[1]));
  if(!wheel)throw new Error(`No locked wheel: ${name}`);
  let data;
  const hosts=['https://pypi.tuna.tsinghua.edu.cn','https://mirrors.aliyun.com/pypi','https://mirrors.cloud.tencent.com/pypi','https://files.pythonhosted.org'];
  for(const host of hosts) {
    const url=wheel[1].replace('https://files.pythonhosted.org',host);
    console.log(`Trying ${name} via ${new URL(host).hostname}`);
    try{
      const r=await fetch(url,{signal:AbortSignal.timeout(600000)});
      if(!r.ok){console.log(`HTTP ${r.status}`);continue;}
      console.log(`HTTP ${r.status}; length ${r.headers.get('content-length')}`);
      const chunks=[];let total=0,last=0;
      for await(const chunk of r.body){chunks.push(chunk);total+=chunk.length;if(total-last>5*1024*1024){console.log(`${name}: ${total} bytes`);last=total;}}
      const bytes=Buffer.concat(chunks);
      if(createHash('sha256').update(bytes).digest('hex')!==wheel[2]){console.log('hash mismatch');continue;}
      data=bytes;break;
    }catch(e){console.log(e.message);}
  }
  if(!data)throw new Error(`All sources failed: ${name}`);
  await writeFile(`.tools/wheels/${wheel[1].split('/').at(-1)}`,data);
  console.log(JSON.stringify({name,bytes:data.length}));
}
