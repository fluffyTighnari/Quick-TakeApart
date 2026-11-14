export function fileUriToPath(uri: string): string {
  let text = uri.trim();
  if (text.startsWith("file://")) {
    text = decodeURIComponent(text.slice("file://".length));
    if (/^\/[A-Za-z]:/.test(text)) text = text.slice(1);
  }
  return text.replace(/^"(.*)"$/, "$1");
}

/** Best-effort local path extraction from a browser drop. */
export function extractDropPath(dt: DataTransfer): string {
  const uri = (dt.getData("text/uri-list") || dt.getData("text/plain") || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("#"));
  if (uri) return fileUriToPath(uri);

  const files = Array.from(dt.files || []);
  return files
    .map((file) => (file as File & { path?: string }).path || "")
    .find(Boolean) || "";
}
