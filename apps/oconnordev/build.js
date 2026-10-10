import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { openSite } from "./browser.js";

const root = import.meta.dirname;
const dist = join(root, "dist");
await rm(dist, { recursive: true, force: true });
await mkdir(join(dist, "assets/css"), { recursive: true });
const css = await readFile(join(root, "assets/css/resume.css"));
const hash = createHash("sha256").update(css).digest("hex");
const stylesheet = `/assets/css/resume-${hash}.css`;
await writeFile(join(dist, stylesheet.slice(1)), css);
const html = await readFile(join(root, "index.html"), "utf8");
assert.equal(html.split('href="/assets/css/resume.css"').length, 2);
await writeFile(
  join(dist, "index.html"),
  html.replace('href="/assets/css/resume.css"', `href="${stylesheet}"`),
);
await copyFile(join(root, "favicon.ico"), join(dist, "favicon.ico"));

const site = await openSite(dist);
try {
  const page = await site.context.newPage();
  // PDF width is 8.5in; 0.5in left/right margins leave 720 CSS pixels.
  await page.setViewportSize({ width: 720, height: 900 });
  await page.emulateMedia({ media: "print" });
  await page.goto(site.origin, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  const height = await page.evaluate(() =>
    Math.ceil(Math.max(document.body.scrollHeight, document.body.getBoundingClientRect().height)),
  );
  assert.equal(
    await page
      .locator(".block-content")
      .first()
      .evaluate((element) => getComputedStyle(element).fontSize),
    "16px",
  );
  await page.pdf({
    path: join(dist, "resume.pdf"),
    width: "816px",
    height: `${height + 98}px`,
    margin: { top: "48px", right: "48px", bottom: "48px", left: "48px" },
    scale: 1,
    printBackground: true,
    displayHeaderFooter: false,
    preferCSSPageSize: false,
    tagged: true,
    outline: true,
  });
  const preview = await site.context.newPage();
  await preview.setViewportSize({ width: 1200, height: 630 });
  await preview.setContent(
    `<html><body style="margin:0">${await readFile(join(root, "preview.svg"), "utf8")}</body></html>`,
  );
  await preview.evaluate(() => document.fonts.ready);
  await preview.screenshot({ path: join(dist, "assets/resume-preview.png") });
  assert.deepEqual(site.foreignRequests, [], "Release must not load foreign resources");
  console.log(`Generated continuous PDF: 816 x ${height + 98} CSS px, 12pt body text`);
} finally {
  await site.close();
}
