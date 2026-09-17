import { defineStore } from "pinia";

export const useNoticeStore = defineStore("notice", {
  state: () => ({
    text: "",
    visible: false,
    timer: 0,
  }),
  actions: {
    show(text: string, duration = 1800) {
      this.text = text;
      this.visible = true;
      window.clearTimeout(this.timer);
      this.timer = window.setTimeout(() => {
        this.visible = false;
      }, duration);
    },
    comingSoon(feature?: string) {
      this.show(feature ? `${feature} · Coming soon` : "Coming soon");
    },
    hide() {
      window.clearTimeout(this.timer);
      this.visible = false;
    },
  },
});
