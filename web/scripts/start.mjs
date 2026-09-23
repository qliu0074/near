import {cp} from 'node:fs/promises';
await cp(new URL('../.next/static', import.meta.url), new URL('../.next/standalone/.next/static', import.meta.url), {recursive:true});
await cp(new URL('../public', import.meta.url), new URL('../.next/standalone/public', import.meta.url), {recursive:true});
// Standalone server requires an explicit loopback host for local development.
process.env.HOSTNAME = '127.0.0.1';
await import('../.next/standalone/server.js');
