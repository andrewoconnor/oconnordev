// Bibliography/license hyperlinks and user image content are not executable
// dependencies. Check the bundler's complete import graph and executable loads,
// rather than rejecting all URLs indiscriminately.
export function validateRuntime(meta, source, html) {
  const threeInputs = Object.keys(meta.inputs).filter((path) => /\/three\//.test(path));
  // Three's WebGL, WebGPU and TSL entry points all share three.core.js.
  // KTX2Loader's current transitive addon graph legitimately uses those entries.
  if (
    !threeInputs.includes("node_modules/three/build/three.core.js") ||
    threeInputs.some((path) => !path.startsWith("node_modules/three/")) ||
    !threeInputs.includes("node_modules/three/examples/jsm/loaders/KTX2Loader.js")
  ) {
    throw new Error("Runtime must use a single shared Three installation and KTX2Loader");
  }
  for (const output of Object.values(meta.outputs)) {
    if (output.imports.length) throw new Error("Runtime bundle has unresolved imports");
  }
  for (const input of Object.values(meta.inputs)) {
    if (input.imports.some((entry) => entry.external)) {
      throw new Error("Runtime dependency graph has external imports");
    }
  }
  if (
    /\bimport\s*\(/.test(source) ||
    /\b(?:import|export)\s[^;]*\bfrom\s*["'](?:https?:|[^./])/.test(source) ||
    /\b(?:fetch|importScripts|Worker)\s*\(\s*["']https?:\/\//.test(source) ||
    /https?:\/\/(?:esm\.sh|unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)\b/.test(source)
  ) {
    throw new Error("Runtime bundle has a remote or unbundled executable dependency");
  }
  if (
    /importmap|https?:\/\/(?:esm\.sh|unpkg\.com)/i.test(html) ||
    /(?:src|href)\s*=\s*["'](?:https?:)?\/\//i.test(html)
  ) {
    throw new Error("Generated HTML must load only local runtime assets without an import map");
  }
}
