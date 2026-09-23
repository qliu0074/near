import {queryCache} from './query-cache';

export class ChatFailure extends Error {
  constructor(message: string, readonly safeToRetry: boolean) {super(message);}
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {super(message);}
}

export function errorText(error: unknown): string {
  if (error instanceof TypeError) return 'Connection failed. Check your network and try again.';
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

async function check(response: Response) {
  if (response.ok) return;
  if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('near:unauthorized'));
  const value: unknown = await response.json().catch(() => null);
  const detail = typeof value === 'object' && value !== null && 'detail' in value ? value.detail : null;
  throw new ApiError(typeof detail === 'string' ? detail : `Request failed (${response.status})` , response.status);
}

export async function request<T>(path: string, csrf = '', body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  const verb = method ?? (body === undefined ? 'GET' : 'POST');
  try {
    const response = await fetch(`/v1${path}`, {method: verb, cache: 'no-store', signal,
      credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: body === undefined ? undefined : JSON.stringify(body)});
    await check(response);
    return await response.json() as T;
  } finally {
    // Even a disconnected mutation may have reached the server. Re-read; never replay it.
    if (verb !== 'GET') queryCache.invalidate();
  }
}

export function read<T>(path: string): Promise<T> {
  return queryCache.read(path, signal => request<T>(path, '', undefined, 'GET', signal));
}

export async function streamChat(path: string, csrf: string, body: unknown, onDelta: (text: string) => void, signal: AbortSignal, onWarning?: (message: string) => void): Promise<void> {
  try {
    const response = await fetch(`/v1${path}?stream=true`, {method: 'POST', cache: 'no-store', signal,
      credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(body)});
    await check(response);
    if (!response.body) throw new Error('No reply stream was received.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; let complete = false;
    const processFrame = (frame: string) => {
      const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!data) return;
      const event: unknown = JSON.parse(data);
      if (typeof event !== 'object' || event === null || !('type' in event)) return;
      if (event.type === 'delta' && 'text' in event && typeof event.text === 'string') onDelta(event.text);
      if (event.type === 'done') complete = true;
      if (event.type === 'warning' && 'message' in event && typeof event.message === 'string') onWarning?.(event.message);
      if (event.type === 'error') throw new ChatFailure(
        'message' in event && typeof event.message === 'string' ? event.message : 'The reply was interrupted. Reserved usage needs review; please do not resend.',
        'safe_to_retry' in event && event.safe_to_retry === true); 
    };
    try {
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value, {stream: !chunk.done});
        // Normalize CRLF after accumulating, including a CR/LF split between chunks.
        buffer = buffer.replace(/\r\n/g, '\n');
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
          processFrame(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2);
        }
        if (chunk.done) break;
      }
      if (!complete) throw new Error('Connection lost. The reply has not been confirmed as saved. Check your conversation and usage before trying again. Messages are not resent automatically.');
    } finally {await reader.cancel().catch(() => undefined); reader.releaseLock();}
  } finally {queryCache.invalidate();}
}
