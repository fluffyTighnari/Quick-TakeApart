/** Model text is written as light Markdown; summaries need a clean plain-text form. */
export function plainText(text: string, limit = 0): string {
  const out = (text || "")
    .replace(/\[\[(?:sym|loc):([^|\]]+)(?:\|([^\]]+))?\]\]/g, (_, id, label) => label || id)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,，。；;:：!?！？])/g, "$1$2")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
  return limit > 0 ? out.slice(0, limit) : out;
}
