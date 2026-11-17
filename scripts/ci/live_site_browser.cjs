const assert = require("node:assert/strict");
const path = require("node:path");

const [site, url] = process.argv.slice(2);
assert.ok(["oconnordev", "drumrollworld"].includes(site), "Unknown site");
assert.match(url, /^https:\/\/[a-z0-9.-]+$/);
const { chromium } = require(
  path.join(__dirname, "../..", "apps", site, "node_modules/playwright"),
);
const origin = new URL(url).origin;

async function check(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  try {
    await context.addInitScript(() => {
      window.violations = [];
      window.transcodes = 0;
      document.addEventListener("securitypolicyviolation", (e) =>
        window.violations.push(`${e.effectiveDirective} ${e.blockedURI}`),
      );
      const WorkerOriginal = window.Worker;
      window.Worker = class extends WorkerOriginal {
        constructor(...args) {
          super(...args);
          this.addEventListener("message", (e) => {
            if (e.data?.type === "transcode") window.transcodes++;
          });
        }
      };
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.route("**/*", (route) => {
      const request = new URL(route.request().url());
      if (request.origin !== origin) return route.abort();
      if (/\/images\/globe\/(earth[a-z]+(4k|8k|10k)|stars8k)\.ktx2$/.test(request.pathname)) {
        return route.abort();
      }
      return route.continue();
    });
    const response = await page.goto(`${origin}/`, { waitUntil: "load", timeout: 60000 });
    assert.equal(response.status(), 200);
    if (site === "oconnordev") {
      assert.match(await page.locator("h1#fullname").innerText(), /O'Connor/);
      assert.ok((await page.locator("main section").count()) > 0, "resume sections");
    } else {
      await page.waitForFunction(() => window.transcodes >= 4, null, { timeout: 60000 });
      await page.waitForFunction(() => !document.getElementById("loadingScreen"), null, {
        timeout: 30000,
      });
      assert.equal(await page.locator("#globeViz canvas").count(), 1);
      assert.equal(await page.locator("#globeUnavailable").count(), 0);
      assert.ok((await page.locator("#entryList > .entry-item").count()) > 0, "entries");
    }
    assert.deepEqual(await page.evaluate(() => window.violations), []);
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  try {
    for (let attempt = 1; ; attempt++) {
      try {
        await check(browser);
        break;
      } catch (error) {
        if (attempt === 3) throw error;
        console.error(`Attempt ${attempt} failed, retrying: ${error.message}`);
        await new Promise((resolve) => setTimeout(resolve, 15000 * attempt));
      }
    }
    console.log(`${origin} renders in Chromium with no page errors or CSP violations`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
