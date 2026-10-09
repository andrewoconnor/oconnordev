import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = fileURLToPath(new URL(".", import.meta.url));
const read = (path) => readFileSync(new URL(path, import.meta.url));

test("build emits a local hashed ESM entry and unchanged stylesheet", () => {
  const result = spawnSync(process.execPath, ["build.js"], { cwd: root, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const html = read("dist/index.html").toString();
  assert.match(html, /src="\/assets\/main-[A-Z0-9]+\.js"/);
  assert.doesNotMatch(html, /importmap|esm\.sh|unpkg\.com|src="\/main\.js"/);
  assert.deepEqual(read("dist/styles.css"), read("styles.css"));
});

test("build publishes a small accessible standalone 404 page unchanged", () => {
  assert.ok(existsSync(new URL("dist/404.html", import.meta.url)), "404.html must be published");
  const bytes = read("dist/404.html");
  assert.deepEqual(bytes, read("404.html"));
  assert.ok(bytes.length < 4096, "the error page must stay below 4 KiB");
  const html = bytes.toString();
  assert.match(html, /<!doctype html>/i);
  assert.match(html, /<html lang="en">/);
  assert.match(html, /<meta name="viewport"/);
  assert.match(html, /<title>404[^<]*<\/title>/);
  assert.match(html, /<main>/);
  assert.match(html, /<h1>404[^<]*<\/h1>/);
  assert.match(html, /<a href="\/">[^<]+<\/a>/);
  assert.doesNotMatch(
    html,
    /<script\b|<link\b|<img\b|<iframe\b|<meta[^>]*refresh|\s(?:src|on\w+)\s*=|javascript:|https?:\/\/|url\s*\(/i,
  );
  assert.doesNotMatch(html, /main-[A-Z0-9]+\.js|globe-container|importmap/);
});

test("local fallback is emitted without creating an images tree", () => {
  assert.match(read("main.js").toString(), /src: "\/assets\/question-image.svg"/);
  assert.deepEqual(read("dist/assets/question-image.svg"), read("question-image.svg"));
  assert.equal(existsSync(new URL("dist/images", import.meta.url)), false);
});

test("notices include every bundled npm package and embedded texture libraries", () => {
  const notices = read("dist/THIRD-PARTY-NOTICES.txt").toString();
  const meta = JSON.parse(read("dist/build-meta.json"));
  const packages = new Set(
    Object.keys(meta.inputs).flatMap((input) => {
      const match = input.match(/^node_modules\/((?:@[^/]+\/)?[^/]+)\//);
      return match ? [match[1]] : [];
    }),
  );
  for (const name of packages) {
    const pkg = JSON.parse(read(`node_modules/${name}/package.json`));
    assert.ok(notices.includes(`${pkg.name}@${pkg.version}`), name);
    const license = readdirSync(new URL(`node_modules/${name}`, import.meta.url)).find((file) =>
      /^license(?:\.|$)/i.test(file),
    );
    assert.ok(notices.includes(read(`node_modules/${name}/${license}`).toString().trim()), name);
  }
  for (const name of ["Basis Universal", "ktx-parse", "zstddec", "Zstandard"]) {
    assert.ok(notices.includes(name), name);
  }
  assert.match(notices, /Apache License/);
  assert.match(notices, /Redistribution and use/);
});

test("build validator rejects remote or bare executable dependency imports", async () => {
  const { validateRuntime } = await import("./runtime-validation.js");
  const meta = JSON.parse(read("dist/build-meta.json"));
  const entry = Object.keys(meta.outputs).find((file) => meta.outputs[file].entryPoint);
  const source = read(entry).toString();
  const html = read("dist/index.html").toString();
  assert.doesNotThrow(() => validateRuntime(meta, source, html));
  for (const code of [
    'import("https://cdn.example/dep.js")',
    'fetch("https://unpkg.com/dep.js")',
    'import("three")',
  ]) {
    assert.throws(() => validateRuntime(meta, `${source}\n${code}`, html), /dependency/);
  }
  const external = structuredClone(meta);
  external.outputs[entry].imports.push({ path: "three", external: true, kind: "import-statement" });
  assert.throws(() => validateRuntime(external, source, html), /imports/);
  assert.throws(
    () => validateRuntime(meta, source, `${html}<script type="importmap">{}</script>`),
    /HTML/,
  );
  const duplicate = structuredClone(meta);
  duplicate.inputs["node_modules/three-globe/node_modules/three/build/three.core.js"] = {
    bytes: 1,
    imports: [],
  };
  assert.throws(() => validateRuntime(duplicate, source, html), /single shared Three/);
});

test("pinned Three basis assets match upstream bytes and local preloads", () => {
  const pkg = JSON.parse(read("package.json"));
  const lock = JSON.parse(read("package-lock.json"));
  assert.equal(pkg.dependencies.three, "0.186.1");
  assert.equal(pkg.dependencies["globe.gl"], "2.46.2");
  assert.equal(pkg.devDependencies.esbuild, "0.28.2");
  assert.equal(pkg.overrides.three, pkg.dependencies.three);
  const threePackages = Object.keys(lock.packages).filter((key) =>
    /(?:^|\/)node_modules\/three$/.test(key),
  );
  assert.deepEqual(threePackages, ["node_modules/three"]);
  assert.equal(lock.packages["node_modules/three"].version, pkg.dependencies.three);
  const basis = `/assets/basis-${pkg.dependencies.three}/`;
  assert.ok(read("main.js").toString().includes(`setTranscoderPath("${basis}")`));
  for (const file of ["basis_transcoder.js", "basis_transcoder.wasm"]) {
    assert.deepEqual(
      read(`dist${basis}${file}`),
      read(`node_modules/three/examples/jsm/libs/basis/${file}`),
    );
    for (const html of ["index.html", "dist/index.html"]) {
      assert.ok(read(html).toString().includes(`href="${basis}${file}"`), html);
      assert.doesNotMatch(read(html).toString(), /importmap|esm\.sh|unpkg\.com/);
    }
  }
  const meta = JSON.parse(read("dist/build-meta.json"));
  assert.ok(meta.inputs["data.js"]);
  assert.ok(meta.inputs["node_modules/globe.gl/dist/globe.gl.mjs"]);
  assert.equal(Object.keys(meta.inputs).filter((key) => key.endsWith("/three.core.js")).length, 1);
});

test("clean builds produce byte-identical artifacts and valid JavaScript", () => {
  const snapshot = () =>
    Object.fromEntries(
      readdirSync(new URL("dist", import.meta.url), { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => {
          const path = `${entry.parentPath}/${entry.name}`;
          return [
            path.slice(root.length),
            createHash("sha256").update(readFileSync(path)).digest("hex"),
          ];
        })
        .sort(([a], [b]) => a.localeCompare(b)),
    );
  const before = snapshot();
  execFileSync(process.execPath, ["build.js"], { cwd: root });
  assert.deepEqual(snapshot(), before);
  for (const file of Object.keys(before).filter((path) => path.endsWith(".js"))) {
    execFileSync(process.execPath, ["--check", file], { cwd: root });
  }
});
