const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

test("canonical base64 fixtures preserve original manifest hashes and lengths", () => {
  const { readFixtures } = require("./fixture-reader.cjs");
  const fixtures = readFixtures(path.join(__dirname, "fixtures"));
  assert.equal(fixtures["kodim23.ktx2"].length, 510819);
  assert.equal(fixtures["kodim18_64x64.png"].length, 10798);
  assert.equal(fixtures["kodim23.ktx2"].subarray(0, 12).toString("hex"), "ab4b5458203230bb0d0a1a0a");
  assert.equal(fixtures["kodim18_64x64.png"].subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
});

test("fixture decoding fails closed for noncanonical encoding, hash, length and missing bytes", () => {
  const { readFixtures } = require("./fixture-reader.cjs");
  const temp = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), "site-fixture-"));
  try {
    const source = path.join(__dirname, "fixtures");
    fs.cpSync(source, temp, { recursive: true });
    const file = path.join(temp, "kodim18_64x64.png.base64");
    const original = fs.readFileSync(file, "utf8");
    for (const invalid of [original.slice(0, -1), original + "\n", original.replace(/.$/m, "!"), original.replace(/=\n$/, "\n"), original.replace(/=\n$/, "B=\n"), original.replace("iVBOR", "iVBO R"), original.replace(/=\n$/, "R=\n")]) {
      fs.writeFileSync(file, invalid);
      assert.throws(() => readFixtures(temp), /canonical base64/);
    }
    fs.writeFileSync(file, original.replace(/^i/, "j"));
    assert.throws(() => readFixtures(temp), /Fixture checksum/);
    fs.writeFileSync(file, Buffer.from("short").toString("base64") + "\n");
    assert.throws(() => readFixtures(temp), /Fixture length/);
    fs.unlinkSync(file);
    assert.throws(() => readFixtures(temp), /ENOENT/);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
