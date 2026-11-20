export type ReadingScale = "compact" | "comfortable" | "large";
export type CodeTheme = "light" | "dark";

const SCALE_KEY = "qta.reading-scale";
const CODE_THEME_KEY = "qta.code-theme";

function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function persist(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage can be unavailable in a locked-down webview */
  }
}

export function initialReadingScale(): ReadingScale {
  const value = stored(SCALE_KEY);
  return value === "compact" || value === "large" || value === "comfortable"
    ? value
    : "comfortable";
}

export function initialCodeTheme(): CodeTheme {
  return stored(CODE_THEME_KEY) === "dark" ? "dark" : "light";
}

export function applyReadingScale(scale: ReadingScale, save = true) {
  document.documentElement.dataset.reading = scale;
  if (save) persist(SCALE_KEY, scale);
}

export function applyCodeTheme(theme: CodeTheme, save = true) {
  document.documentElement.dataset.codeTheme = theme;
  if (save) persist(CODE_THEME_KEY, theme);
}

export function initUiPreferences() {
  applyReadingScale(initialReadingScale(), false);
  applyCodeTheme(initialCodeTheme(), false);
}

export const READING_SCALE_LABEL: Record<ReadingScale, string> = {
  compact: "紧凑",
  comfortable: "舒适",
  large: "大号",
};
