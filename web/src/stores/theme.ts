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

function updateThemeColor(dark: boolean): void {
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#09090b" : "#fafafa");
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    dark: true,
    preference: "system" as "system" | "light" | "dark",
    systemListenerBound: false,
  }),
  actions: {
    apply(persist = true) {
      document.documentElement.classList.toggle("dark", this.dark);
      updateThemeColor(this.dark);
      if (persist) localStorage.setItem(STORAGE_KEY, this.dark ? "dark" : "light");
    },
    toggle() {
      this.setDark(!this.dark);
    },
    setDark(dark: boolean) {
      this.dark = dark;
      this.preference = dark ? "dark" : "light";
      this.apply();
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
      updateThemeColor(this.dark);
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
