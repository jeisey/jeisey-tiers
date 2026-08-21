import { chromium } from "@playwright/test";
const args = process.argv.slice(2);
const url = args[0], out = args[1], w = Number(args[2]), h = Number(args[3]);
const full = args[4] === "full";
const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: w, height: h } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(400);
if (process.env.SHOT_SCRIPT) { await page.evaluate(process.env.SHOT_SCRIPT); await page.waitForTimeout(400); }
await page.screenshot({ path: out, fullPage: full });
const info = await page.evaluate(() => {
  const doc = document.documentElement;
  const overflow = doc.scrollWidth - doc.clientWidth;
  const wide = [...document.querySelectorAll("*")]
    .filter((el) => el.getBoundingClientRect().right > doc.clientWidth + 1)
    .slice(0, 8)
    .map((el) => `${el.tagName}.${el.className && typeof el.className === 'string' ? el.className.split(' ')[0] : ''}=${Math.round(el.getBoundingClientRect().right)}`);
  return { overflow, wide };
});
console.log(JSON.stringify({ errors, ...info }));
await browser.close();
