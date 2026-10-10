// Opt-in real-browser regression. Reuses installed Playwright/Chromium and
// genuine KTX2/JPEG fixtures; no downloads, installs or cloud writes here.
// KTX2_FIXTURE=/path/to/genuine.ktx2 JPEG_FIXTURE=/path/to/image.jpg
// CHROMIUM=/path/to/chrome-headless-shell node scripts/drumrollworld/test/background-browser.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "../../../apps/oconnordev/node_modules/playwright",
);
const root = path.resolve(__dirname, "../../..");
const dist = path.join(root, "apps/drumrollworld/dist");
const ktx = fs.readFileSync(process.env.KTX2_FIXTURE);
const jpeg = fs.readFileSync(process.env.JPEG_FIXTURE);
assert.deepEqual(
  ktx.subarray(0, 12),
  Buffer.from([0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a]),
);
const csp = fs
  .readFileSync(path.join(root, "infra/aws/drumrollworld/static-site-delivery.tf"), "utf8")
  .match(/content_security_policy\s*=\s*"([^"]+)"/)[1];
const mime = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".wasm": "application/wasm",
  ".svg": "image/svg+xml",
};
async function scenario(browser, mode, expected) {
  const requests = [];
  let releaseInitial, releaseBackground;
  const initialGate = new Promise((r) => {
    releaseInitial = r;
  });
  const backgroundGate = new Promise((r) => {
    releaseBackground = r;
  });
  let active = 0,
    peak = 0;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost").pathname;
    res.setHeader("Content-Security-Policy", csp);
    if (url.endsWith(".ktx2")) {
      requests.push(url);
      active++;
      peak = Math.max(peak, active);
      if (url.includes("earthnormal2k")) await initialGate;
      if (mode === "zoom" && /earth(map|normal|spec)4k/.test(url)) await backgroundGate;
      await new Promise((r) => setTimeout(r, 80));
      active--;
      res.setHeader("Content-Type", "image/ktx2");
      if (mode === "fallback") {
        res.statusCode = 404;
        res.end("unavailable");
      } else res.end(ktx);
    } else if (url.startsWith("/images/")) {
      res.setHeader("Content-Type", "image/jpeg");
      res.end(jpeg);
    } else {
      const file = path.join(dist, url === "/" ? "index.html" : url);
      if (!fs.existsSync(file)) {
        res.statusCode = 404;
        res.end("missing");
        return;
      }
      res.setHeader("Content-Type", mime[path.extname(file)] || "text/plain");
      res.end(fs.readFileSync(file));
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const context = await browser.newContext({
    viewport: mode === "phone" ? { width: 390, height: 844 } : { width: 1440, height: 900 },
  });
  try {
    await context.addInitScript(
      ({ mode }) => {
        // SwiftShader's real ceiling is often 8192. Exercise the desktop 10k
        // scheduling path with an emulated capability; fixture dimensions stay tiny.
        if (mode === "desktop" || mode === "zoom") {
          const getParameter = WebGL2RenderingContext.prototype.getParameter;
          WebGL2RenderingContext.prototype.getParameter = function (name) {
            const value = getParameter.call(this, name);
            if (name === this.MAX_TEXTURE_SIZE) {
              window.hardwareMaxTextureSize = value;
              return 16384;
            }
            return value;
          };
        }
        if (mode === "save-data")
          Object.defineProperty(navigator, "connection", { value: { saveData: true } });
        window.transcodes = [];
        window.violations = [];
        document.addEventListener("securitypolicyviolation", (e) =>
          window.violations.push(e.effectiveDirective),
        );
        const WorkerOriginal = Worker;
        window.Worker = class extends WorkerOriginal {
          constructor(...args) {
            super(...args);
            this.addEventListener("message", (e) => {
              if (e.data.type === "transcode")
                window.transcodes.push(e.data.data.faces[0].mipmaps.length);
            });
          }
        };
      },
      { mode },
    );
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/*", (route) =>
      route.request().url().startsWith(origin) ? route.continue() : route.abort(),
    );
    await page.goto(origin, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelector("canvas"));
    // Let three initial textures finish while the normal map is held open.
    await page.waitForTimeout(700);
    assert.equal(requests.length, 4, `${mode}: no background fetch before first tier settles`);
    releaseInitial();
    if (mode === "zoom") {
      await page.waitForFunction(() => window.transcodes.length >= 4);
      for (let i = 0; i < 100 && !requests.some((p) => p.includes("earthmap4k")); i++)
        await page.waitForTimeout(50);
      assert.ok(requests.some((p) => p.includes("earthmap4k")));
      await page.mouse.move(1050, 450);
      for (let i = 0; i < 8; i++) {
        await page.mouse.wheel(0, -600);
        await page.waitForTimeout(100);
      }
      assert.ok(
        !requests.some((p) => p.includes("earthmap10k")),
        "zoom cannot overlap the held 4k tier",
      );
      releaseBackground();
    }
    await page
      .waitForFunction((n) => window.transcodes.length === n, expected, { timeout: 30000 })
      .catch(async (e) => {
        console.error({
          mode,
          requests,
          errors,
          transcodes: await page.evaluate(() => window.transcodes),
          violations: await page.evaluate(() => window.violations),
        });
        throw e;
      });
    await page.waitForFunction(() => !document.getElementById("loadingScreen"));
    await page.waitForTimeout(800);
    assert.equal(await page.evaluate(() => window.transcodes.length), expected);
    assert.equal(peak <= 4, true, `${mode}: bounded network concurrency, got ${peak}`);
    assert.deepEqual(await page.evaluate(() => window.violations), []);
    assert.deepEqual(errors, []);
    assert.equal(await page.locator("#globeUnavailable").count(), 0);
    if (mode === "desktop") assert.ok(requests.some((p) => p.includes("earthmap10k")));
    if (mode === "phone") {
      assert.ok(requests.some((p) => p.includes("earthmap8k")));
      assert.ok(!requests.some((p) => p.includes("10k")));
    }
    if (mode === "save-data" || mode === "fallback") assert.equal(requests.length, 4);
    if (mode === "zoom") {
      assert.ok(requests.some((p) => p.includes("earthmap10k")));
      assert.ok(
        !requests.some((p) => p.includes("earthmap8k")),
        "zoom jumps ahead of background 8k",
      );
    }
    const title = await page.locator("#activeTitle").innerText();
    await page.locator("#nextBtn").click();
    assert.notEqual(await page.locator("#activeTitle").innerText(), title);
    await page.locator("#searchBar").fill("zzzznotfoundzzzz");
    assert.equal(await page.locator("#entryList > .entry-item").count(), 0);
    await page.locator("#searchBar").fill("");
    if (process.env.BROWSER_SCREENSHOT && mode === "desktop")
      await page.screenshot({ path: process.env.BROWSER_SCREENSHOT });
    return {
      mode,
      transcodes: expected,
      peakRequests: peak,
      requests,
      pageErrors: errors.length,
      cspViolations: 0,
    };
  } finally {
    releaseInitial();
    releaseBackground();
    await context.close();
    await new Promise((r) => server.close(r));
  }
}
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM,
    headless: true,
    args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  try {
    const reports = [];
    for (const [mode, expected] of [
      ["desktop", 14],
      ["phone", 11],
      ["save-data", 4],
      ["fallback", 0],
      ["zoom", 11],
    ])
      reports.push(await scenario(browser, mode, expected));
    console.log(JSON.stringify(reports, null, 2));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
