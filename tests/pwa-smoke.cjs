const assert = require('node:assert/strict');
const {chromium} = require('../web/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.NEAR_BROWSER_CHANNEL ? {channel:process.env.NEAR_BROWSER_CHANNEL} : {})});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = []; page.on('pageerror',error => errors.push(error.message));
    await page.goto('http://localhost:3000/offline.html');
    await page.evaluate(async () => {
      const legacy = await caches.open('near-public-v1');
      await legacy.put('/offline.html', new Response('旧的中文离线页面'));
    });
    await page.goto('http://localhost:3000');
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    assert(!(await page.evaluate(() => caches.keys())).includes('near-public-v1'));
    const manifest = await (await context.request.get('http://localhost:3000/manifest.webmanifest')).json();
    assert.equal(manifest.display,'standalone'); assert.equal(manifest.start_url,'/');
    assert.equal(manifest.lang,'en');
    for (const icon of manifest.icons) {
      const response = await context.request.get(`http://localhost:3000${icon.src}`);
      assert.equal(response.status(),200); assert.match(response.headers()['content-type'],/image\/png/);
    }
    const worker = await context.request.get('http://localhost:3000/sw.js');
    assert.match(worker.headers()['cache-control'],/no-store/);
    await page.getByLabel('Email',{exact:true}).fill(`pwa-${Date.now()}@example.com`);
    await page.getByRole('button',{name:'Send code',exact:true}).click();
    const notice = page.locator('.notice'); await notice.waitFor();
    await page.getByLabel('Verification code',{exact:true}).fill((await notice.textContent()).match(/\d{6}/)[0]);
    await page.getByRole('button',{name:'Sign in / Sign up →',exact:true}).click();
    await page.getByRole('button',{name:'Sign out',exact:true}).waitFor();
    await page.getByLabel('Name',{exact:true}).fill('Offline companion');
    await page.getByLabel('Background, personality, and appearance').fill('An original fictional forest companion');
    await page.getByRole('checkbox').check();
    await page.getByRole('button',{name:'Let the story begin →'}).click();
    const composer = page.getByPlaceholder('Share a little about your day…'); await composer.waitFor();
    await composer.fill('这条已保存的私密消息不能进入离线缓存');
    await page.getByRole('button',{name:'Send ↑'}).click();
    await page.locator('.message.assistant').filter({hasText:'Local demo'}).waitFor();
    const secret = '仅在内存中的私密草稿';
    await composer.fill(secret);
    let posts = 0;
    page.on('request',request => {if (request.method() === 'POST' && request.url().includes('/messages')) posts++;});
    await context.setOffline(true);
    await page.getByText('You are offline. Your draft stays on this page. Send it manually when you reconnect.',{exact:true}).waitFor();
    assert(await page.getByRole('button',{name:'Send ↑'}).isDisabled());
    assert.equal(await composer.inputValue(),secret);
    await context.setOffline(false);
    await page.getByText('● Live sync connected',{exact:true}).waitFor();
    assert.equal(await composer.inputValue(),secret); assert.equal(posts,0);
    const cachePaths = await page.evaluate(async () => {
      const paths = [];
      for (const name of await caches.keys()) for (const request of await (await caches.open(name)).keys()) paths.push(new URL(request.url).pathname);
      return paths;
    });
    assert(cachePaths.includes('/offline.html'));
    assert(cachePaths.every(path => path === '/offline.html' || path === '/manifest.webmanifest' || path.startsWith('/icons/') || path.startsWith('/_next/static/')));
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length),0);
    await context.setOffline(true);
    await page.reload();
    await page.getByRole('heading',{name:'You are offline',exact:true}).waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert(!/\p{Script=Han}/u.test(await page.locator('body').innerText()));
    assert.equal(await page.getByText(secret,{exact:true}).count(),0);
    // Cached authenticated API responses must never be available offline.
    assert.equal(await page.evaluate(async () => {
      try {await fetch('/v1/account/export'); return false;} catch {return true;}
    }),true);
    await context.setOffline(false);
    await page.getByRole('link',{name:'Reconnect'}).click();
    await page.getByRole('button',{name:'Sign out',exact:true}).waitFor();
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await page.getByRole('button',{name:'Sign in / Sign up →',exact:true}).waitFor();
    assert.equal(await page.locator('.message').count(),0);
    await page.getByLabel('Email',{exact:true}).fill(`pwa-other-${Date.now()}@example.com`);
    await page.getByRole('button',{name:'Send code',exact:true}).click();
    await notice.waitFor();
    await page.getByLabel('Verification code',{exact:true}).fill((await notice.textContent()).match(/\d{6}/)[0]);
    await page.getByRole('button',{name:'Sign in / Sign up →',exact:true}).click();
    await page.getByRole('heading',{name:'Who would you like to meet?'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Offline companion Fictional person'}).count(),0);
    assert.equal(await page.locator('.message').count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: manifest/icons, SW registration, static-only cache, offline fallback, draft retention, no automatic sends, reconnect, logout');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
