// Render docs/*.png from the labeled example snapshot.
// Requires Playwright (not a runtime dependency of the dashboard):
//   npm install playwright && npx playwright install chromium
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const playwrightSpec = process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
  : "playwright";
const { chromium } = await import(playwrightSpec);

const root = fileURLToPath(new URL("../site/public/", import.meta.url));
const docs = fileURLToPath(new URL("../docs/", import.meta.url));
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, "");
  const path = join(root, rel === "/" ? "index.html" : rel);
  if (!path.startsWith(root)) {
    response.writeHead(403).end("forbidden");
    return;
  }
  try {
    const body = await readFile(path);
    response.writeHead(200, { "content-type": types[extname(path)] || "application/octet-stream" });
    response.end(body);
  } catch {
    response.writeHead(404).end("not found");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 1200 },
  locale: "zh-CN",
  timezoneId: "America/New_York",
  colorScheme: "dark",
});
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));
await page.goto(`http://127.0.0.1:${port}/?example=1`, { waitUntil: "networkidle" });
await page.waitForSelector("#banner:not([hidden])");
const banner = await page.locator("#banner").innerText();
if (!banner.includes("示例") || !/example/i.test(banner)) {
  throw new Error("example banner missing: " + banner);
}
await page.getByText("预估准确度").waitFor();
await page.getByText("校准约").first().waitFor();
const accuracyText = await page.locator("#accuracy").innerText();
if (!accuracyText.includes("1.10×") || !accuracyText.includes("1.45×")) {
  throw new Error("accuracy table does not show the example ratios:\n" + accuracyText);
}
await page.screenshot({ path: join(docs, "screenshot-dashboard.png") });
await page.locator("#accuracy").screenshot({ path: join(docs, "screenshot-accuracy.png") });

await page.evaluate(() => window.scrollTo(0, 0));
await page.getByRole("button", { name: "EN" }).click();
await page.getByText("Estimate accuracy").waitFor();
await page.getByText("Running").first().waitFor();
await page.screenshot({ path: join(docs, "screenshot-dashboard-en.png") });

await page.evaluate(() => window.scrollTo(0, 0));
await page.setViewportSize({ width: 390, height: 844 });
await page.screenshot({ path: join(docs, "screenshot-mobile.png") });

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
}
await browser.close();
server.close();
console.log("wrote docs/screenshot-*.png");
