import { defineStore } from "pinia";

const STORAGE_KEY = "musico-theme";

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStoredTheme(): boolean | null {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "dark") return true;
  if (saved === "light") return false;
  return null;
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    dark: true,
  }),
  actions: {
    apply() {
      document.documentElement.classList.toggle("dark", this.dark);
      localStorage.setItem(STORAGE_KEY, this.dark ? "dark" : "light");
    },
    toggle() {
      this.setDark(!this.dark);
    },
    setDark(dark: boolean) {
      this.dark = dark;
      this.apply();
    },
    followSystem() {
      this.dark = systemPrefersDark();
      this.apply();
    },
    init() {
      const stored = readStoredTheme();
      this.dark = stored ?? systemPrefersDark();
      document.documentElement.classList.toggle("dark", this.dark);
    },
  },
});
