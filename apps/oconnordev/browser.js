import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve, sep } from "node:path";
import { chromium } from "playwright";

// Local Chromium is convenient for development; CI installs Playwright's pinned browser.
export async function openSite(root) {
  const directory = resolve(root);
  const server = createServer(async (request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    const file = resolve(directory, `.${pathname === "/" ? "/index.html" : pathname}`);
    if (!file.startsWith(`${directory}${sep}`)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const content = await readFile(file);
      const type = file.endsWith(".html")
        ? "text/html"
        : file.endsWith(".css")
          ? "text/css"
          : file.endsWith(".js")
            ? "text/javascript"
            : file.endsWith(".pdf")
              ? "application/pdf"
              : file.endsWith(".png")
                ? "image/png"
                : "image/x-icon";
      response.writeHead(200, { "Content-Type": type }).end(content);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    const executablePath =
      process.env.CHROMIUM_PATH ||
      (process.env.CI !== "true" && existsSync("/usr/bin/chromium")
        ? "/usr/bin/chromium"
        : undefined);
    browser = await chromium.launch({ executablePath, headless: true, args: ["--no-sandbox"] });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      serviceWorkers: "block",
    });
    const foreignRequests = [];
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) {
        foreignRequests.push(url.href);
        return route.abort();
      }
      return route.continue();
    });
    return {
      context,
      origin,
      foreignRequests,
      close: async () => {
        await browser.close();
        await new Promise((resolve) => server.close(resolve));
      },
    };
  } catch (error) {
    await browser?.close();
    await new Promise((resolve) => server.close(resolve));
    throw error;
  }
}
