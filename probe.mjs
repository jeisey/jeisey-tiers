import { chromium } from "@playwright/test";
const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
await page.goto(process.argv[2], { waitUntil: "networkidle" });
await page.waitForTimeout(400);
const info = await page.evaluate(() => {
  const doc = document.documentElement;
  const scroll = document.querySelector(".table-scroll");
  const base = doc.scrollWidth;
  const out = { base };
  const hide = (sel) => {
    const nodes = [...scroll.querySelectorAll(sel)];
    const prev = nodes.map((n) => n.style.display);
    nodes.forEach((n) => { n.style.display = "none"; });
    const v = doc.scrollWidth;
    nodes.forEach((n, i) => { n.style.display = prev[i]; });
    return v;
  };
  out.caption = hide("caption");
  out.thead = hide("thead");
  out.tbody = hide("tbody");
  out.badges = hide(".visually-hidden");
  return out;
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
