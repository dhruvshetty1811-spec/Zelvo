// Download a pinned release and verify its published SHA-256. No remote script execution.
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import tls from 'node:tls';
import { fileURLToPath } from 'node:url';

const tools = fileURLToPath(new URL('../.tools/', import.meta.url));
await mkdir(tools, { recursive: true });
const base = 'https://github.com/astral-sh/uv/releases/download/0.9.17/uv-x86_64-pc-windows-msvc.zip';
const response = await fetch(base);
if (!response.ok) throw new Error(`uv download failed: ${response.status}`);
const archive = Buffer.from(await response.arrayBuffer());
const checksum = await fetch(base + '.sha256');
if (!checksum.ok) throw new Error(`uv checksum download failed: ${checksum.status}`);
const expected = (await checksum.text()).trim().split(/\s+/)[0];
const actual = createHash('sha256').update(archive).digest('hex');
if (actual !== expected) throw new Error('uv checksum mismatch');
await writeFile(new URL('../.tools/uv.zip', import.meta.url), archive);
// Export public trust anchors for Python/uv on certificate-intercepting networks.
const certificates = [...new Set([...tls.getCACertificates('default'), ...tls.getCACertificates('system')])];
await writeFile(new URL('../.tools/ca-bundle.pem', import.meta.url), certificates.join('\n'));
console.log('Downloaded and verified uv 0.9.17.');
