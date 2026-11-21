// Runs the map's `?bench=1` measurement in headless Chrome (the installed one, using the GPU) and prints the result.
//   pnpm bench [url] [--throttle 4]      (url defaults to the API serving the built page; add ?renderer=geojson to compare)
import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const at = args.indexOf(name);
  return at === -1 ? fallback : args[at + 1];
};
const url = args.find((arg) => arg.startsWith("http")) ?? "http://localhost:8000/";
const throttle = Number(option("--throttle", "1"));

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--enable-gpu", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));
await page.goto(`${url}${url.includes("?") ? "&" : "?"}bench=1`);
// After navigating: the page may move to a new renderer process, which wouldn't be throttled
if (throttle > 1) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: throttle });
}
const renderer = await page.evaluate(() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  const info = gl?.getExtension("WEBGL_debug_renderer_info");
  return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "unknown";
});
await page.waitForFunction(() => window.__bench, null, { timeout: 120_000, polling: 1000 });
const result = await page.evaluate(() => window.__bench);
console.log(JSON.stringify({ url, throttle, gpu: renderer, ...result, errors: errors.length }));
await browser.close();
