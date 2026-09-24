import { defineStore } from "pinia";

const STORAGE_KEY = "musico-theme";
const STYLE_STORAGE_KEY = "musico-style-theme";

export const STYLE_THEMES = [
  { id: "minimal", name: "简" },
  { id: "pulse", name: "动" },
  { id: "glaze", name: "炫" },
] as const;
export type StyleThemeId = (typeof STYLE_THEMES)[number]["id"];
const DEFAULT_STYLE_THEME: StyleThemeId = "minimal";

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStoredTheme(): boolean | null {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "dark") return true;
  if (saved === "light") return false;
  return null;
}

function isStyleThemeId(value: string | null): value is StyleThemeId {
  return STYLE_THEMES.some((item) => item.id === value);
}

function readStoredStyleTheme(): StyleThemeId | null {
  const saved = localStorage.getItem(STYLE_STORAGE_KEY);
  return isStyleThemeId(saved) ? saved : null;
}

function themeColor(dark: boolean, style: StyleThemeId): string {
  if (style === "glaze") return dark ? "#070b14" : "#eef4fb";
  if (!dark && style === "minimal") return "#e4ded4";
  return dark ? "#09090b" : "#fafafa";
}

function updateThemeColor(dark: boolean, style: StyleThemeId): void {
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", themeColor(dark, style));
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    dark: true,
    preference: "system" as "system" | "light" | "dark",
    styleTheme: DEFAULT_STYLE_THEME as StyleThemeId,
    systemListenerBound: false,
  }),
  getters: {
    styleThemes: () => STYLE_THEMES,
    isGlaze: (state) => state.styleTheme === "glaze",
    isPulse: (state) => state.styleTheme === "pulse",
  },
  actions: {
    apply(persist = true) {
      document.documentElement.classList.toggle("dark", this.dark);
      updateThemeColor(this.dark, this.styleTheme);
      if (persist) localStorage.setItem(STORAGE_KEY, this.dark ? "dark" : "light");
    },
    applyStyle(persist = true) {
      document.documentElement.dataset.theme = this.styleTheme;
      updateThemeColor(this.dark, this.styleTheme);
      if (persist) localStorage.setItem(STYLE_STORAGE_KEY, this.styleTheme);
    },
    toggle() {
      this.setDark(!this.dark);
    },
    setDark(dark: boolean) {
      this.dark = dark;
      this.preference = dark ? "dark" : "light";
      this.apply();
    },
    setStyleTheme(id: StyleThemeId) {
      this.styleTheme = id;
      this.applyStyle();
    },
    followSystem() {
      this.preference = "system";
      this.dark = systemPrefersDark();
      localStorage.removeItem(STORAGE_KEY);
      this.apply(false);
    },
    init() {
      const stored = readStoredTheme();
      this.preference = stored == null ? "system" : stored ? "dark" : "light";
      this.dark = stored ?? systemPrefersDark();
      document.documentElement.classList.toggle("dark", this.dark);
      updateThemeColor(this.dark, this.styleTheme);
      const storedStyle = readStoredStyleTheme();
      this.styleTheme = storedStyle ?? DEFAULT_STYLE_THEME;
      if (storedStyle == null) localStorage.removeItem(STYLE_STORAGE_KEY);
      this.applyStyle(false);
      if (!this.systemListenerBound) {
        this.systemListenerBound = true;
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
          if (this.preference !== "system") return;
          this.dark = event.matches;
          this.apply(false);
        });
      }
    },
  },
});
