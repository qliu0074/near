// Render the repository's vector mark into the PNG sizes used by PWA installers.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
(async () => {
  const directory = path.join(__dirname, '../public/icons');
  const svg = await fs.readFile(path.join(directory, 'icon.svg'), 'utf8');
  const browser = await chromium.launch({headless: true,
    ...(process.env.NEAR_BROWSER_CHANNEL ? {channel: process.env.NEAR_BROWSER_CHANNEL} : {})});
  try {
    const page = await browser.newPage({deviceScaleFactor: 1});
    for (const [name, size] of [['icon-192.png',192], ['icon-512.png',512], ['icon-maskable.png',512], ['apple-touch-icon.png',180]]) {
      await page.setViewportSize({width:size,height:size});
      await page.setContent(`<style>body{margin:0}svg{display:block;width:100vw;height:100vh}</style>${svg}`);
      await page.screenshot({path:path.join(directory,name)});
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
