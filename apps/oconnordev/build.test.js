import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { relative } from "node:path";
import { test } from "node:test";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { openSite } from "./browser.js";

const compact = (text) => text.replaceAll("•", "").replace(/\s+/g, "");

test("production PDF is one continuous readable page containing every resume claim and link", async () => {
  const pdfPath = new URL("./dist/resume.pdf", import.meta.url);
  assert.ok(existsSync(pdfPath), "Build must generate a real resume.pdf");
  const task = getDocument({
    data: new Uint8Array(await readFile(pdfPath)),
    useSystemFonts: true,
    isEvalSupported: false,
  });
  const document = await task.promise;
  try {
    assert.equal(document.numPages, 1);
    const page = await document.getPage(1);
    const content = await page.getTextContent();
    const text = compact(content.items.map((item) => item.str).join(" "));
    const baseline = JSON.parse(
      await readFile(new URL("./resume-content.json", import.meta.url), "utf8"),
    );
    for (const [section, claim] of Object.entries(baseline)) {
      assert.ok(text.includes(compact(claim)), `PDF omitted or reordered content: ${section}`);
    }
    for (const identity of [
      "Andrew Vincent O'Connor",
      "Senior Site Reliability Engineer",
      "AI Security, Multi-Cloud & ML Infrastructure",
      "andrewoconnor@outlook.com",
      "301-624-9886",
      "Made with",
      "in Baltimore, MD",
    ]) {
      assert.ok(text.includes(compact(identity)), `Missing identity: ${identity}`);
    }
    const [left, bottom, right, top] = page.view;
    assert.ok(top > 792, "Must not shrink onto Letter paper");
    assert.ok(top < 14400, "Custom page must stay within common PDF viewer limits");
    for (const item of content.items.filter((item) => item.str.trim())) {
      const [, , , , x, y] = item.transform;
      assert.ok(x >= left + 30 && x + item.width <= right - 30, `Horizontal clipping: ${item.str}`);
      assert.ok(y >= bottom + 30 && y + item.height <= top - 30, `Vertical clipping: ${item.str}`);
      assert.ok(item.height >= 11.9, `Unreadably scaled text: ${item.str} (${item.height}pt)`);
    }
    const links = (await page.getAnnotations())
      .map((annotation) => annotation.url || annotation.unsafeUrl)
      .filter(Boolean);
    for (const url of [
      "mailto:andrewoconnor@outlook.com",
      "tel:+13016249886",
      "https://oconnor.dev/",
      "https://github.com/andrewoconnor",
      "https://www.linkedin.com/in/andrewvoconnor",
      "https://drumroll.world/",
      "https://www.credly.com/badges/8348bfc9-7864-4b23-8d73-ad4183853982",
    ]) {
      assert.ok(links.includes(url), `Missing PDF link: ${url}`);
    }
    console.log(
      JSON.stringify({
        pages: document.numPages,
        widthPt: right,
        heightPt: top,
        textItems: content.items.length,
        links: links.length,
        baselineSections: Object.keys(baseline).length,
      }),
    );
  } finally {
    await task.destroy();
  }
});

test("release publishes only deployable assets with a real 1200x630 preview and downloadable PDF", async () => {
  const dist = new URL("./dist/", import.meta.url);
  const files = (await readdir(dist, { recursive: true, withFileTypes: true }))
    .filter((entry) => entry.isFile())
    .map((entry) => relative(dist.pathname, `${entry.parentPath}/${entry.name}`))
    .sort();
  const html = await readFile(new URL("./dist/index.html", import.meta.url), "utf8");
  const href = html.match(/<link href="([^"]+)" rel="stylesheet">/)?.[1];
  assert.match(href || "", /^\/assets\/css\/resume-[0-9a-f]{64}\.css$/);
  const css = await readFile(new URL(`./dist${href}`, import.meta.url));
  const hash = createHash("sha256").update(css).digest("hex");
  assert.equal(
    href,
    `/assets/css/resume-${hash}.css`,
    "URL must address the actual deployed bytes",
  );
  assert.deepEqual(css, await readFile(new URL("./assets/css/resume.css", import.meta.url)));
  assert.deepEqual(files, [
    href.slice(1),
    "assets/resume-preview.png",
    "favicon.ico",
    "index.html",
    "resume.pdf",
  ]);
  const image = await readFile(new URL("./dist/assets/resume-preview.png", import.meta.url));
  assert.equal(image.subarray(1, 4).toString(), "PNG");
  assert.equal(image.readUInt32BE(16), 1200);
  assert.equal(image.readUInt32BE(20), 630);
  const site = await openSite(dist.pathname);
  try {
    const page = await site.context.newPage();
    const failedResponses = [];
    page.on("response", (response) => {
      if (!response.ok()) failedResponses.push(response.url());
    });
    await page.goto(site.origin);
    const previewUrl = await page.locator('meta[property="og:image"]').getAttribute("content");
    const preview = await page.request.get(`${site.origin}${new URL(previewUrl).pathname}`);
    assert.equal(preview.status(), 200);
    assert.equal(preview.headers()["content-type"], "image/png");
    const downloadEvent = page.waitForEvent("download");
    await page.locator("#printResume").click();
    const download = await downloadEvent;
    assert.equal(download.suggestedFilename(), "Andrew-Vincent-OConnor-Resume.pdf");
    assert.deepEqual(
      await readFile(await download.path()),
      await readFile(new URL("./dist/resume.pdf", import.meta.url)),
    );
    assert.deepEqual(failedResponses, []);
    assert.deepEqual(site.foreignRequests, []);
  } finally {
    await site.close();
  }
});
