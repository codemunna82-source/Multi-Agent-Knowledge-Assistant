export type Theme = "system" | "light" | "dark";
const KEY = "mka_theme";

export function loadTheme(): Theme {
  try { const v = localStorage.getItem(KEY); if (v === "light" || v === "dark" || v === "system") return v; } catch { /* storage may be blocked */ }
  return "system";
}

/** Sets data-theme on <html>; "system" removes it so the prefers-color-scheme media query decides. */
export function applyTheme(t: Theme) {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", t);
  try { localStorage.setItem(KEY, t); } catch { /* ignore */ }
}
