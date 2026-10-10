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
  assert.equal(await page.locator('svg.icon[width="1em"][height="1em"]').count(), 6);
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

for (const stale of [false, true]) {
  for (const [width, media, size] of [
    [375, "screen", 12],
    [390, "screen", 12],
    [1280, "screen", 14],
    [720, "print", 16],
  ]) {
    test(`icons and contact text remain compact at ${width}px ${media}, stale CSS: ${stale}`, async () => {
      const current = await readFile(new URL("./assets/css/resume.css", import.meta.url), "utf8");
      // Minimal stale-stylesheet reproduction: the pre-icon release had no .icon rule.
      const css = stale ? current.replace(/\.icon\s*\{[^}]*\}/, "") : current;
      const mobile = await site.context.newPage();
      try {
        await mobile.setViewportSize({ width, height: 900 });
        await mobile.emulateMedia({ media });
        let intercepted = false;
        await mobile.route("**/assets/css/resume.css", async (route) => {
          intercepted = true;
          await route.fulfill({ contentType: "text/css", body: css });
        });
        await mobile.goto(site.origin, { waitUntil: "networkidle" });
        assert.ok(intercepted, "Must exercise the stylesheet response");
        const icons = await mobile.locator("svg.icon").evaluateAll((elements) =>
          elements.map((element) => {
            const rect = element.getBoundingClientRect();
            return {
              width: rect.width,
              height: rect.height,
              hidden: getComputedStyle(element.parentElement).display === "none",
            };
          }),
        );
        assert.equal(icons.length, 6);
        for (const icon of icons) {
          if (icon.hidden) {
            assert.equal(media, "print");
            assert.equal(icon.width, 0);
            continue;
          }
          assert.ok(Math.abs(icon.width - size) < 0.1, JSON.stringify(icon));
          assert.ok(Math.abs(icon.height - size) < 0.1, JSON.stringify(icon));
        }
        for (const [href, text] of [
          ["mailto:andrewoconnor@outlook.com", "andrewoconnor@outlook.com"],
          ["tel:", "301-624-9886"],
          ["https://oconnor.dev", "oconnor.dev"],
          ["https://github.com/andrewoconnor", "GitHub"],
          ["https://www.linkedin.com/in/andrewvoconnor", "LinkedIn"],
        ]) {
          const link = mobile.locator(`a[href^="${href}"]`);
          assert.equal((await link.innerText()).trim(), text);
          const rect = await link.boundingBox();
          assert.ok(rect && rect.x >= 0 && rect.x + rect.width <= width && rect.height < size * 2);
          const textRect = await link.evaluate((element) => {
            const range = document.createRange();
            range.selectNodeContents(element);
            const rects = [...range.getClientRects()].filter((rect) => rect.width > 0);
            return rects.every((rect) => rect.right <= innerWidth && rect.bottom < innerHeight);
          });
          assert.ok(textRect, "Contact text must fit within the initial viewport");
        }
        assert.ok(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      } finally {
        await mobile.close();
      }
    });
  }
}

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
