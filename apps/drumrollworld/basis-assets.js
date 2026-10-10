// Repository transport is UTF-8; deployed WASM remains the pinned binary.
export function decodeBasisWasm(text) {
  const encoded = text.endsWith("\n") ? text.slice(0, -1) : text;
  if (
    !encoded ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)
  ) {
    throw new Error("Vendored Basis WASM must be canonical Base64");
  }
  const bytes = Buffer.from(encoded, "base64");
  if (bytes.toString("base64") !== encoded) {
    throw new Error("Vendored Basis WASM must be canonical Base64");
  }
  return bytes;
}
