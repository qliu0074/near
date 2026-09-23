// Run with the Playwright package installed, or the bundled runtime available.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES + '/playwright' : '../web/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.NEAR_BROWSER_CHANNEL ? {channel:process.env.NEAR_BROWSER_CHANNEL} : {})});
  try {
  // UI route fixtures require bypassing the service worker; pwa-smoke tests it separately.
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, serviceWorkers:'block'});
  const page = await context.newPage();
  fs.mkdirSync(path.join(__dirname, '../test-results'), {recursive:true});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const email = `test-${Date.now()}@example.com`;
  async function signIn(target) {
    await target.goto('http://localhost:3000');
    await target.getByLabel('Email', {exact:true}).fill(email);
    assert.equal(await target.locator('html').getAttribute('lang'), 'en');
    assert(!/\p{Script=Han}/u.test(await target.locator('body').innerText()));
    await target.getByRole('button', {name:'Send code', exact:true}).click();
    const notice = target.locator('.notice');
    await notice.waitFor();
    const text = await notice.textContent();
    const code = text.match(/\d{6}/)[0];
    await target.getByLabel('Verification code', {exact:true}).fill(code);
    await target.getByRole('button', {name:'Sign in / Sign up →', exact:true}).click();
    await target.getByRole('button', {name:'Sign out', exact:true}).waitFor();
  }
  await signIn(page);
  await page.getByLabel('Name', {exact:true}).fill('Sprout');
  await page.getByLabel('Type', {exact:true}).selectOption('animal');
  await page.getByLabel('Background, personality, and appearance').fill('A fictional fox who lives in a forest bookshop and enjoys rainy days and quiet company.');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', {name:'Let the story begin →'}).click();
  await page.getByPlaceholder('Share a little about your day…').waitFor();
  const multilingual = '我今天完成了自己的第一个项目 · Hola, ¿cómo estás? · こんにちは · مرحبًا 👋';
  await page.getByPlaceholder('Share a little about your day…').fill(multilingual);
  await page.getByRole('button', {name:'Send ↑'}).click();
  await page.locator('.message.assistant').filter({hasText:'Local demo'}).waitFor();
  await page.locator('.message.user').waitFor();
  assert.equal(await page.locator('.message.user p').textContent(), multilingual);
  assert.equal(await page.locator('.message.user').count(), 1);
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name:'Save as memory', exact:true}).first().click();
  await page.getByRole('button', {name:'Memories · 1', exact:true}).waitFor();
  await page.getByRole('button', {name:'Memories · 1', exact:true}).click();
  await page.getByRole('button', {name:'Delete memory', exact:true}).waitFor();
  assert(await page.getByRole('button', {name:'Portraits unavailable · No charge'}).isDisabled());
  await page.screenshot({path:path.join(__dirname, '../test-results/desktop.png'),fullPage:true});
  // Separate browser context represents a second device with the same valid session.
  const second = await browser.newContext({storageState:await context.storageState(),viewport:{width:390,height:844},serviceWorkers:'block'});
  const phone = await second.newPage();
  phone.on('pageerror', e => errors.push(e.message));
  await phone.goto('http://localhost:3000');
  await phone.getByRole('button', {name:'Sprout Animal companion'}).click();
  await phone.locator('.message.user').waitFor();
  await page.getByPlaceholder('Share a little about your day…').fill('这是第二台设备应该看到的消息');
  await page.getByRole('button', {name:'Send ↑'}).click();
  await phone.getByText('这是第二台设备应该看到的消息', {exact:true}).waitFor({timeout:10000});
  assert(await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await phone.screenshot({path:path.join(__dirname, '../test-results/mobile.png'),fullPage:true});
  let failHistory = true;
  const historyFailure = async route => {
    if (route.request().method() === 'GET' && failHistory) return route.fulfill({status:503,json:{detail:'Test read failure'}});
    return route.continue();
  };
  await page.route('**/v1/companions/*/messages*', historyFailure);
  await page.reload();
  await page.getByRole('button', {name:'Sprout Animal companion'}).click();
  await page.getByText('Test read failure', {exact:false}).waitFor();
  failHistory = false;
  await page.getByRole('button', {name:'Reload', exact:true}).click();
  await page.locator('.message.assistant').first().waitFor();
  await page.unroute('**/v1/companions/*/messages*', historyFailure);
  // Controlled history fixture exercises pagination while the real SSE service runs.
  const history = Array.from({length:51}, (_, i) => ({id:`history-${String(i).padStart(3,'0')}`,
    role:'user', content:`分页记录 ${i}`, created:1700000000+i}));
  let historyRequests = 0;
  await page.route('**/v1/companions/*/messages*', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    historyRequests++;
    const before = new URL(route.request().url()).searchParams.get('before');
    const items = before ? history.filter(item => item.created < Number(before)) : history;
    await route.fulfill({json:items.slice(-50)});
  });
  await page.reload();
  await page.getByRole('button', {name:'Sprout Animal companion'}).click();
  await page.getByRole('button', {name:'Load earlier messages', exact:true}).click();
  await page.getByText('分页记录 0', {exact:true}).waitFor();
  assert.equal(await page.getByRole('button', {name:'Load earlier messages', exact:true}).count(), 0);
  const requestsBeforeSync = historyRequests;
  await phone.getByPlaceholder('Share a little about your day…').fill('مرحبًا، كيف كان يومك؟');
  assert.equal(await phone.locator('#message').evaluate(element => getComputedStyle(element).direction), 'rtl');
  await phone.getByRole('button', {name:'Send ↑'}).click();
  const arabicMessage = phone.locator('.message.user p').filter({hasText:'مرحبًا، كيف كان يومك؟'});
  await arabicMessage.waitFor();
  assert.equal(await arabicMessage.evaluate(element => getComputedStyle(element).direction), 'rtl');
  for (let attempt = 0; historyRequests < requestsBeforeSync + 2 && attempt < 50; attempt++) {
    await page.waitForTimeout(200);
  }
  assert(historyRequests >= requestsBeforeSync + 2, 'SSE must refresh all loaded history pages');
  await page.getByText('分页记录 0', {exact:true}).waitFor();
  assert.equal(await page.locator('.message.user').count(), 51);
  await page.getByRole('button', {name:'Sign out all devices',exact:true}).click();
  await page.getByRole('button', {name:'Sign in / Sign up →',exact:true}).waitFor();
  await phone.reload();
  await phone.getByRole('button', {name:'Sign in / Sign up →',exact:true}).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: email login, creation, streamed chat, confirmed memory, disabled portrait API, two-context sync, mobile width, history pagination and sync, revoke all sessions, no browser errors');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
