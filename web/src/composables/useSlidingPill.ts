import { nextTick, onMounted, onUnmounted, ref, watch, type Ref } from "vue";

export function useSlidingPill(root: Ref<HTMLElement | null>, deps: () => unknown) {
  const pill = ref({ left: "0px", width: "0px", opacity: "0" });
  let observer: ResizeObserver | null = null;

  function measure() {
    const parent = root.value;
    if (!parent?.getClientRects().length) return;
    const active = parent.querySelector<HTMLElement>('[data-nav-on="true"]');
    if (!active) {
      pill.value = { ...pill.value, opacity: "0" };
      return;
    }
    pill.value = {
      left: `${active.offsetLeft}px`,
      width: `${active.offsetWidth}px`,
      opacity: "1",
    };
  }

  function bind(el: HTMLElement | null) {
    observer?.disconnect();
    observer = null;
    if (!el) return;
    observer = new ResizeObserver(() => measure());
    observer.observe(el);
    void nextTick(measure);
  }

  onMounted(() => {
    bind(root.value);
    window.addEventListener("resize", measure);
  });
  watch(root, (el) => bind(el));
  watch(deps, () => void nextTick(measure), { flush: "post" });
  onUnmounted(() => {
    observer?.disconnect();
    window.removeEventListener("resize", measure);
  });

  return pill;
}
