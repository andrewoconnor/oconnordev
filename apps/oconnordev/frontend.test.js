import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, before, test } from "node:test";
import { openSite } from "./browser.js";

let site;
let page;
before(async () => {
  site = await openSite(import.meta.dirname);
  page = await site.context.newPage();
  await page.goto(site.origin);
});
after(async () => site?.close());

test("metadata describes the actual resume and canonical identity", async () => {
  const metadata = await page.evaluate(() => ({
    description: document.querySelector('meta[name="description"]')?.content,
    canonical: document.querySelector('link[rel="canonical"]')?.href,
    og: Object.fromEntries(
      [...document.querySelectorAll('meta[property^="og:"]')].map((tag) => [
        tag.getAttribute("property"),
        tag.content,
      ]),
    ),
    person: JSON.parse(
      document.querySelector('script[type="application/ld+json"]')?.textContent || "null",
    ),
  }));
  assert.match(
    metadata.description || "",
    /Andrew Vincent O'Connor.*Senior Site Reliability Engineer/,
  );
  assert.equal(metadata.canonical, "https://oconnor.dev/");
  assert.equal(metadata.og["og:url"], metadata.canonical);
  assert.equal(metadata.og["og:title"], await page.title());
  assert.equal(metadata.og["og:description"], metadata.description);
  assert.equal(metadata.og["og:type"], "website");
  assert.equal(metadata.og["og:image"], "https://oconnor.dev/assets/resume-preview.png");
  assert.equal(metadata.person["@type"], "Person");
  assert.equal(metadata.person.name, "Andrew Vincent O'Connor");
  assert.equal(metadata.person.jobTitle, "Senior Site Reliability Engineer");
  assert.equal(metadata.person.url, metadata.canonical);
  assert.deepEqual(metadata.person.sameAs, [
    "https://github.com/andrewoconnor",
    "https://www.linkedin.com/in/andrewvoconnor",
  ]);
  assert.ok(metadata.person.knowsAbout.includes("AI security"));
});

test("resume has semantic headings and valid lists without changing baseline content", async () => {
  assert.equal(await page.locator("main").count(), 1);
  assert.equal(await page.locator("h1").count(), 1);
  assert.equal((await page.locator("h1").innerText()).trim(), "Andrew Vincent O'Connor");
  assert.equal(await page.locator("section > h2").count(), 7);
  assert.equal(await page.locator("h3.block-title").count(), 19);
  assert.equal(await page.locator("#experience .block-content > ul").count(), 7);
  assert.equal(await page.locator("ul > :not(li), ul ul:not(li > ul)").count(), 0);
  assert.equal(await page.locator("#experience p").count(), 0);
  const content = await page.evaluate(() =>
    Object.fromEntries(
      [...document.querySelectorAll("section")].map((element) => [
        element.id,
        element.textContent.replaceAll("•", "").replace(/\s+/g, " ").trim(),
      ]),
    ),
  );
  assert.deepEqual(
    content,
    JSON.parse(await readFile(new URL("./resume-content.json", import.meta.url), "utf8")),
  );
});

test("all resources are local and all six icons are decorative inline SVG", async () => {
  assert.deepEqual(site.foreignRequests, []);
  assert.equal(await page.locator("i, link[href^='https://']:not([rel='canonical'])").count(), 0);
  assert.equal(await page.locator("svg[aria-hidden='true'][focusable='false']").count(), 6);
  assert.equal(await page.locator("script:not([type='application/ld+json'])").count(), 0);
});

test("contacts and download are actionable, visible links with keyboard focus", async () => {
  assert.equal(
    (await page.locator('a[href="mailto:andrewoconnor@outlook.com"]').innerText()).trim(),
    "andrewoconnor@outlook.com",
  );
  assert.equal(
    (await page.locator('a[href="tel:+13016249886"]').innerText()).trim(),
    "301-624-9886",
  );
  assert.equal(
    (await page.locator('a[href="https://www.linkedin.com/in/andrewvoconnor"]').innerText()).trim(),
    "LinkedIn",
  );
  assert.equal(await page.locator("#printResume").getAttribute("href"), "/resume.pdf");
  assert.equal(
    await page.locator("#printResume").getAttribute("download"),
    "Andrew-Vincent-OConnor-Resume.pdf",
  );
  for (const link of await page.locator("a").all()) {
    assert.match(
      await link.evaluate((element) => getComputedStyle(element).textDecorationLine),
      /underline/,
    );
  }
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(":focus-visible").count(), 1);
  assert.notEqual(
    await page
      .locator(":focus-visible")
      .evaluate((element) => getComputedStyle(element).outlineStyle),
    "none",
  );
});

test("dates and footer exceed 4.5:1 contrast on white and mobile has no overflow", async () => {
  const colors = await page
    .locator(".block-subtitle, footer")
    .evaluateAll((elements) => elements.map((element) => getComputedStyle(element).color));
  for (const color of colors) {
    const rgb = color.match(/\d+/g).map(Number);
    const linear = rgb.map((value) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    const contrast = 1.05 / (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2] + 0.05);
    assert.ok(contrast >= 4.5, `${color}: ${contrast}`);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
});
