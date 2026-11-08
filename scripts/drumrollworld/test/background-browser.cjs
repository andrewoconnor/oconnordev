const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { readFixtures } = require("../../security/fixture-reader.cjs");
const root = path.resolve(__dirname, "../../..");
const { chromium } = require(path.join(root, "apps/drumrollworld/node_modules/playwright"));
const dist = path.join(root, "apps/drumrollworld/dist");
const fixtures = readFixtures(path.join(root, "scripts/security/fixtures"));
const ktx = fixtures["kodim23.ktx2"];
const image = fixtures["kodim18_64x64.png"];
assert.deepEqual(
  ktx.subarray(0, 12),
  Buffer.from([0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a]),
);
const csp = fs
  .readFileSync(path.join(root, "infra/aws/drumrollworld/site.tf"), "utf8")
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
  const held = [];
  const arrivalWaiters = [];
  let served = 0;
  const arrived = (count) =>
    requests.length >= count
      ? Promise.resolve()
      : new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error(`${mode}: expected ${count} KTX2 requests`)),
            30000,
          );
          arrivalWaiters.push({
            count,
            resolve: () => {
              clearTimeout(timer);
              resolve();
            },
          });
        });
  const release = (items) => {
    for (const item of items) {
      held.splice(held.indexOf(item), 1);
      served++;
      item.release();
    }
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost").pathname;
    res.setHeader("Content-Security-Policy", csp);
    if (url.endsWith(".ktx2")) {
      requests.push(url);
      for (const waiter of arrivalWaiters.filter((w) => requests.length >= w.count)) {
        arrivalWaiters.splice(arrivalWaiters.indexOf(waiter), 1);
        waiter.resolve();
      }
      if (mode === "fallback") {
        res.statusCode = 404;
        res.end("unavailable");
        return;
      }
      await new Promise((resolve) => held.push({ url, release: resolve }));
      res.setHeader("Content-Type", "image/ktx2");
      res.end(ktx);
    } else if (url.startsWith("/images/")) {
      res.setHeader("Content-Type", "image/png");
      res.end(image);
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
  const errors = [];
  let page;
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
        window.ktxFetches = [];
        window.transcodesAtFetch = [];
        window.openKtxFetches = 0;
        window.peakKtxFetches = 0;
        window.appIdleCallbacks = 0;
        document.addEventListener("securitypolicyviolation", (e) =>
          window.violations.push(e.effectiveDirective),
        );
        const fetchOriginal = window.fetch;
        window.fetch = function (input, init) {
          const url = new URL(typeof input === "string" ? input : input.url, location.href);
          if (!url.pathname.endsWith(".ktx2")) return fetchOriginal.call(this, input, init);
          window.ktxFetches.push(url.pathname);
          window.transcodesAtFetch.push(window.transcodes.length);
          window.peakKtxFetches = Math.max(window.peakKtxFetches, ++window.openKtxFetches);
          return fetchOriginal.call(this, input, init).finally(() => window.openKtxFetches--);
        };
        const idleOriginal = window.requestIdleCallback;
        window.requestIdleCallback = function (...args) {
          window.appIdleCallbacks++;
          return idleOriginal.apply(this, args);
        };
        window.settle = () =>
          new Promise((resolve) =>
            idleOriginal(() => requestAnimationFrame(() => setTimeout(resolve)), {
              timeout: 10000,
            }),
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
    page = await context.newPage();
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/*", (route) =>
      route.request().url().startsWith(origin) ? route.continue() : route.abort(),
    );
    const peak = () => page.evaluate(() => window.peakKtxFetches);
    const quiesce = async () => {
      await page.waitForFunction((count) => window.transcodes.length === count, served);
      await page.evaluate(() => window.settle());
      const open = await peak();
      assert.ok(open <= 4, `${mode}: bounded network concurrency, got ${open}`);
      await arrived(await page.evaluate(() => window.ktxFetches.length));
    };
    const releaseTier = async () => {
      const [last, ...rest] = held;
      const before = requests.length;
      release(rest);
      await quiesce();
      assert.deepEqual(
        held.map((item) => item.url),
        [last.url],
        `${mode}: no fetch starts before every texture of the current tier is transcoded`,
      );
      assert.equal(requests.length, before, `${mode}: no fetch starts before the tier completes`);
      release([last]);
      const transcoded = served;
      await quiesce();
      const startedAt = await page.evaluate((from) => window.transcodesAtFetch.slice(from), before);
      assert.ok(
        startedAt.every((count) => count === transcoded),
        `${mode}: the next tier starts only after the current tier is transcoded, got ${startedAt}`,
      );
    };
    await page.goto(origin, { waitUntil: "domcontentloaded" });
    await arrived(4);
    if (mode === "fallback") await quiesce();
    let zoomed = false;
    for (let round = 1; held.length; round++) {
      assert.ok(round <= 4, `${mode}: more than 4 texture tiers were requested`);
      if (mode === "zoom" && !zoomed && held.some((item) => item.url.includes("earthmap4k"))) {
        zoomed = true;
        await page.mouse.move(1050, 450);
        for (let i = 0; i < 8; i++) await page.mouse.wheel(0, -600);
        await quiesce();
        assert.ok(
          !requests.some((p) => p.includes("earthmap10k")),
          "zoom cannot overlap the held 4k tier",
        );
      }
      await releaseTier();
    }
    assert.equal(mode === "zoom", zoomed, `${mode}: zoom ran only in zoom mode`);
    if (mode !== "fallback" && mode !== "save-data")
      assert.ok(
        (await page.evaluate(() => window.appIdleCallbacks)) > 0,
        `${mode}: background upgrades must still start from requestIdleCallback`,
      );
    await page.waitForFunction(() => !document.getElementById("loadingScreen"));
    assert.equal(await page.evaluate(() => window.transcodes.length), expected);
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
    await page.evaluate(() => window.settle());
    assert.deepEqual((await page.evaluate(() => window.ktxFetches)).sort(), [...requests].sort());
    assert.equal(held.length, 0, `${mode}: no fetch starts after the last tier`);
    const finalPeak = await peak();
    assert.ok(finalPeak <= 4, `${mode}: bounded network concurrency, got ${finalPeak}`);
    if (process.env.BROWSER_SCREENSHOT && mode === "desktop")
      await page.screenshot({ path: process.env.BROWSER_SCREENSHOT });
    return {
      mode,
      transcodes: expected,
      peakRequests: finalPeak,
      requests,
      pageErrors: errors.length,
      cspViolations: 0,
    };
  } catch (error) {
    console.error({
      mode,
      requests,
      held: held.map((item) => item.url),
      errors,
      transcodes: await page?.evaluate(() => window.transcodes).catch(() => null),
      violations: await page?.evaluate(() => window.violations).catch(() => null),
    });
    throw error;
  } finally {
    release([...held]);
    await context.close();
    server.closeAllConnections();
    await new Promise((r) => server.close(r));
  }
}
(async () => {
  const browser = await chromium.launch({
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
