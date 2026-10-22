import deployment from './deployment.json';

// The public Vercel frontend uses Render; local and same-origin deployments
// retain /api. An explicit build environment setting overrides this mapping.
const configuredOrigin = (import.meta.env.VITE_ZELVO_API_URL?.trim() ||
  (location.origin === deployment.frontend_origin ? deployment.simulation_origin : '')).replace(/\/$/, '');
export function apiUrl(path: string): string {
  return `${configuredOrigin}${path}`;
}
export function streamUrl(path: string): string {
  const url = new URL(apiUrl(path), location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
