<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { coverImageUrl, type CoverImageSize } from "../lib/cover-image";

const props = withDefaults(
  defineProps<{
    src: string | null | undefined;
    alt?: string;
    size?: CoverImageSize;
    eager?: boolean;
  }>(),
  {
    alt: "",
    size: 150,
    eager: false,
  },
);

const failed = ref(false);
const url = computed(() => coverImageUrl(props.src, props.size));

watch(url, () => {
  failed.value = false;
});
</script>

<template>
  <img
    v-if="url && !failed"
    :src="url"
    :alt="alt"
    :loading="eager ? 'eager' : 'lazy'"
    decoding="async"
    referrerpolicy="no-referrer"
    @error="failed = true"
  />
  <div
    v-else
    role="img"
    :aria-label="alt || '暂无封面'"
    class="grid h-full w-full place-items-center bg-zinc-200 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
  >
    <svg viewBox="0 0 24 24" class="h-1/3 w-1/3" fill="none" aria-hidden="true">
      <path
        d="M9 17V6l9-2v11M9 9l9-2M9 17a3 3 0 1 1-3-3h3v3Zm9-2a3 3 0 1 1-3-3h3v3Z"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  </div>
</template>
