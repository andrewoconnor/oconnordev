import { mkdir, readFile, readdir, rm, copyFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { validateRuntime } from "./runtime-validation.js";

const root = fileURLToPath(new URL(".", import.meta.url));
const dist = join(root, "dist");
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
const result = await build({
  absWorkingDir: root,
  entryPoints: { main: "main.js" },
  outdir: "dist/assets",
  entryNames: "[name]-[hash]",
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  minify: true,
  legalComments: "linked",
  metafile: true,
  charset: "utf8",
  logLevel: "warning",
});
const [entry, output] = Object.entries(result.metafile.outputs).find(
  ([, value]) => value.entryPoint,
);
if (output.imports.length) throw new Error("Runtime bundle must not contain external imports");
const html = (await readFile(join(root, "index.html"), "utf8")).replace(
  'src="/main.js"',
  `src="/${entry.replace("dist/", "")}"`,
);
validateRuntime(result.metafile, await readFile(join(root, entry), "utf8"), html);
await writeFile(join(dist, "index.html"), html);
await copyFile(join(root, "styles.css"), join(dist, "styles.css"));
await copyFile(join(root, "question-image.svg"), join(dist, "assets/question-image.svg"));
const basis = "assets/basis-0.186.1";
await mkdir(join(dist, basis), { recursive: true });
for (const file of ["basis_transcoder.js", "basis_transcoder.wasm"]) {
  await copyFile(
    join(root, "node_modules/three/examples/jsm/libs/basis", file),
    join(dist, basis, file),
  );
}
// Include complete license/notice files for every package in the bundling graph,
// including transitive and tree-shaken modules. Inline legal comments also ship
// next to the bundle in esbuild's linked .LEGAL.txt artifact.
const packagePaths = new Set(
  Object.keys(result.metafile.inputs).flatMap((input) => {
    const match = input.match(/^(node_modules\/(?:@[^/]+\/)?[^/]+)\//);
    return match ? [match[1]] : [];
  }),
);
let notices = "DrumrollWorld third-party runtime attribution\n\n";
for (const path of [...packagePaths].sort()) {
  const pkg = JSON.parse(await readFile(join(root, path, "package.json"), "utf8"));
  const files = (await readdir(join(root, path)))
    .filter((file) => /^(license|copying|notice|copyrightnotice)(\.|$)/i.test(file))
    .sort();
  if (!files.some((file) => /^license(\.|$)/i.test(file))) {
    throw new Error(`Missing license text for ${pkg.name}@${pkg.version}`);
  }
  notices += `===== ${pkg.name}@${pkg.version} (${pkg.license}) =====\n`;
  for (const file of files) {
    notices += `\n--- ${file} ---\n${(await readFile(join(root, path, file), "utf8")).trim()}\n`;
  }
  notices += "\n";
}
notices += await readFile(join(root, "third-party/EMBEDDED-LICENSES.txt"), "utf8");
notices +=
  "\nOriginal question-image.svg fallback: created for DrumrollWorld; no third-party artwork.\n";
await writeFile(join(dist, "THIRD-PARTY-NOTICES.txt"), notices);
await writeFile(join(dist, "build-meta.json"), `${JSON.stringify(result.metafile, null, 2)}\n`);
console.log(`Built ${entry} (${output.bytes} bytes)`);
