// Manifest hashes and lengths always describe the original upstream binary bytes.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

function readFixtures(directory) {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, "provenance.json"), "utf8"));
  return Object.fromEntries(Object.entries(manifest.files).map(([name, metadata]) => {
    const encoded = fs.readFileSync(path.join(directory, `${name}.base64`), "utf8");
    const payload = encoded.slice(0, -1);
    assert.ok(encoded.endsWith("\n") && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(payload), `Fixture canonical base64: ${name}`);
    const bytes = Buffer.from(payload, "base64");
    assert.equal(bytes.toString("base64") + "\n", encoded, `Fixture canonical base64: ${name}`);
    assert.equal(bytes.length, metadata.bytes, `Fixture length: ${name}`);
    assert.equal(crypto.createHash("sha256").update(bytes).digest("hex"), metadata.sha256, `Fixture checksum: ${name}`);
    return [name, bytes];
  }));
}

module.exports = { readFixtures };
