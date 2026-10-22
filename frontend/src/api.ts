// Set this when the frontend and the live SUMO service use different origins.
const configuredOrigin = (import.meta.env.VITE_ZELVO_API_URL ?? '').trim().replace(/\/$/, '');
export function apiUrl(path: string): string {
  return `${configuredOrigin}${path}`;
}
export function streamUrl(path: string): string {
  const url = new URL(apiUrl(path), location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
