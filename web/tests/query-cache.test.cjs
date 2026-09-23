require('./load-typescript.cjs');
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {QueryCache, CancelledRead} = require('../lib/query-cache.ts');

test('deduplicates concurrent reads and reuses a fresh response', async () => {
  const cache = new QueryCache(); let calls = 0;
  const loader = async () => {calls++; return {name:'Near'};};
  const [one,two] = await Promise.all([cache.read('/me',loader),cache.read('/me',loader)]);
  assert.equal(one,two); assert.equal(calls,1);
  assert.equal(await cache.read('/me',loader),one); assert.equal(calls,1);
});

test('expired data is revalidated; capacity evicts the least recently used read', async () => {
  const expired = new QueryCache(0);
  await expired.read('a',async () => 1);
  assert.equal(await expired.read('a',async () => 2),2);
  const cache = new QueryCache(10000,2);
  await cache.read('a',async () => 1); await cache.read('b',async () => 2);
  assert.equal(cache.peek('a'),1);
  await cache.read('c',async () => 3);
  assert.equal(cache.peek('b'),undefined); assert.equal(cache.peek('a'),1);
});

test('logout/invalidation cancels old responses even when a loader ignores abort', async () => {
  const cache = new QueryCache(); let resolve; let oldSignal;
  const old = cache.read('/me',signal => {oldSignal = signal; return new Promise(done => {resolve = done;});});
  await Promise.resolve();
  const cancelled = assert.rejects(old,CancelledRead);
  cache.invalidate(); assert.equal(oldSignal.aborted,true);
  assert.equal(cache.peek('/me'),undefined);
  await cache.read('/me',async () => 'new account');
  resolve('old account'); await cancelled;
  assert.equal(cache.peek('/me'),'new account');
});

test('errors are not cached or retried, and subscribers can unsubscribe', async () => {
  const cache = new QueryCache(); let calls = 0; let changes = 0;
  const unsubscribe = cache.subscribe(() => changes++);
  await assert.rejects(cache.read('a',async () => {calls++; throw new Error('offline');}));
  assert.equal(calls,1); assert.equal(cache.peek('a'),undefined);
  assert.equal(await cache.read('a',async () => 'retry'),'retry');
  cache.invalidate(); unsubscribe(); cache.invalidate(); assert.equal(changes,1);
});
