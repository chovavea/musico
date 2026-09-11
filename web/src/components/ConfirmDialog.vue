<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from "vue";
import AppIcon from "./AppIcon.vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description: string;
    confirmLabel?: string;
    busy?: boolean;
  }>(),
  {
    confirmLabel: "确认",
    busy: false,
  },
);

const emit = defineEmits<{ confirm: []; cancel: [] }>();
const confirmButton = ref<HTMLButtonElement | null>(null);
const dialog = ref<HTMLElement | null>(null);
let previousFocus: HTMLElement | null = null;

function onKeydown(event: KeyboardEvent) {
  if (!props.open) return;
  if (event.key === "Escape" && !props.busy) {
    event.preventDefault();
    emit("cancel");
    return;
  }
  if (event.key === "Tab") {
    const focusable = Array.from(
      dialog.value?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]") ?? [],
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      document.addEventListener("keydown", onKeydown);
      await nextTick();
      confirmButton.value?.focus();
      return;
    }
    document.removeEventListener("keydown", onKeydown);
    previousFocus?.focus();
    previousFocus = null;
  },
);

onUnmounted(() => document.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[100] grid place-items-center bg-zinc-950/50 p-4"
      role="presentation"
      @mousedown.self="!busy && emit('cancel')"
    >
      <section
        ref="dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="`${$attrs.id || 'confirm'}-title`"
        :aria-describedby="`${$attrs.id || 'confirm'}-description`"
        class="w-full max-w-sm rounded-2xl bg-white p-5 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
      >
        <h2 :id="`${$attrs.id || 'confirm'}-title`" class="text-lg font-semibold">{{ title }}</h2>
        <p :id="`${$attrs.id || 'confirm'}-description`" class="mt-2 text-sm text-secondary">
          {{ description }}
        </p>
        <div class="mt-5 flex justify-end gap-2">
          <button
            type="button"
            class="h-11 rounded-full px-4 text-sm text-secondary hover:bg-zinc-100 disabled:opacity-50 dark:hover:bg-white/10"
            :disabled="busy"
            @click="emit('cancel')"
          >
            取消
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="inline-flex h-11 items-center gap-2 rounded-full bg-rose-600 px-4 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-70"
            :disabled="busy"
            @click="emit('confirm')"
          >
            <AppIcon v-if="busy" name="spinner" :size="16" />
            {{ busy ? "正在删除" : confirmLabel }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
