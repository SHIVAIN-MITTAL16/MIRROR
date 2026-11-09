const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8002';

const configuredBase = globalThis.MIRROR_API_BASE_URL
  || document.querySelector('meta[name="mirror-api-base-url"]')?.content
  || DEFAULT_API_BASE_URL;

export const API_BASE_URL = configuredBase.replace(/\/+$/, '');

export function apiUrl(path) {
  return new URL(String(path).replace(/^\/+/, ''), `${API_BASE_URL}/`).toString();
}
