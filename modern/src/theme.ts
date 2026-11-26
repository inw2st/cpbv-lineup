export type Theme = "system" | "light" | "dark";
export const THEME_KEY = "cpbv-lineup-theme";
export function readTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (value === "dark" || value === "light") return value;
  } catch {
    /* Backend preferences remain available if browser storage is off. */
  }
  return "system";
}
export function applyTheme(theme: Theme, systemDark: boolean) {
  const mode = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  document.documentElement.dataset.theme = mode;
  document.documentElement.style.colorScheme = mode;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* Saved in Python too. */
  }
}
