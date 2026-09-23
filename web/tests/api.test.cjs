require('./load-typescript.cjs');
const {test, afterEach} = require('node:test');
const assert = require('node:assert/strict');
const {request, streamChat, ApiError} = require('../lib/api.ts');
const {queryCache} = require('../lib/query-cache.ts');
const originalFetch = global.fetch;
afterEach(() => {global.fetch = originalFetch; queryCache.invalidate();});

test('reads bypass persistent HTTP caches; failed writes invalidate without replay', async () => {
  let calls = 0;
  global.fetch = async (_url, options) => {
    calls++; assert.equal(options.cache,'no-store');
    if (options.method === 'POST') throw new TypeError('disconnected');
    return Response.json({ok:true});
  };
  assert.deepEqual(await request('/me'),{ok:true});
  await queryCache.read('private',async () => 'secret');
  await assert.rejects(request('/paid','csrf',{request_id:'one'}));
  assert.equal(calls,2); assert.equal(queryCache.peek('private'),undefined);
});

test('HTTP errors preserve status and server details', async () => {
  global.fetch = async () => Response.json({detail:'quota exceeded'},{status:429});
  await assert.rejects(request('/paid','csrf',{}),error => error instanceof ApiError && error.status === 429 && error.message === 'quota exceeded');
});

function streamed(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({start(controller) {
    // Includes UTF-8 character and CRLF boundaries split across network chunks.
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }}));
}

test('chat decodes fragmented UTF-8 and SSE CRLF frames', async () => {
  global.fetch = async () => streamed(': ping\r\n\r\ndata: {"type":"delta","text":"你好"}\r\n\r\ndata: {"type":"done"}\r\n\r\n');
  let text = '';
  await streamChat('/messages','csrf',{},delta => text += delta,new AbortController().signal);
  assert.equal(text,'你好');
});

test('incomplete paid streams fail once and are never automatically retried', async () => {
  let calls = 0;
  global.fetch = async () => {calls++; return streamed('data: {"type":"delta","text":"partial"}\n\n');};
  await assert.rejects(streamChat('/messages','csrf',{},() => {},new AbortController().signal),/not been confirmed as saved/);
  assert.equal(calls,1);
});


test('chat reports safe rejection and memory degradation without resending', async () => {
  const {ChatFailure} = require('../lib/api.ts');
  let calls = 0;
  global.fetch = async () => {calls++; return streamed('data: {"type":"warning","message":"Memory unavailable"}\n\ndata: {"type":"error","safe_to_retry":true,"message":"Model rejected; reference: abc"}\n\n');};
  let warning = '';
  await assert.rejects(streamChat('/messages','csrf',{},() => {},new AbortController().signal,
    value => warning = value), error => error instanceof ChatFailure && error.safeToRetry && error.message.includes('abc'));
  assert.equal(warning, 'Memory unavailable');
  assert.equal(calls, 1);
});
