<script setup lang="ts">
withDefaults(
  defineProps<{
    name:
      | "play"
      | "pause"
      | "download"
      | "check"
      | "chevron-left"
      | "chevron-right"
      | "chevron-up"
      | "chevron-down"
      | "close"
      | "trash"
      | "more"
      | "external"
      | "refresh"
      | "menu"
      | "search"
      | "spinner";
    size?: number;
  }>(),
  { size: 16 },
);
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    class="shrink-0"
    :class="name === 'spinner' ? 'animate-spin motion-reduce:animate-none' : ''"
  >
    <path
      v-if="name === 'play'"
      d="m9 7 8 5-8 5V7Z"
      fill="currentColor"
      stroke="currentColor"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'pause'"
      d="M9 7v10M15 7v10"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
    />
    <path
      v-else-if="name === 'download'"
      d="M12 4v10m0 0 3.5-3.5M12 14l-3.5-3.5M5 18v1h14v-1"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'check'"
      d="m5 12.5 4.2 4L19 7"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'chevron-left'"
      d="m15 5-7 7 7 7"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'chevron-right'"
      d="m9 5 7 7-7 7"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'chevron-up'"
      d="m5 15 7-7 7 7"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'chevron-down'"
      d="m5 9 7 7 7-7"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'close'"
      d="m6 6 12 12M18 6 6 18"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
    />
    <path
      v-else-if="name === 'trash'"
      d="M8 8v10m4-10v10m4-10v10M5 6h14M9 6V4h6v2m2 0-.7 14H7.7L7 6"
      stroke="currentColor"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'more'"
      d="M6 12h.01M12 12h.01M18 12h.01"
      stroke="currentColor"
      stroke-width="3"
      stroke-linecap="round"
    />
    <path
      v-else-if="name === 'external'"
      d="M13 5h6v6m0-6-9 9M11 7H6a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-5"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'refresh'"
      d="M19 7v5h-5M5 17v-5h5M18 12a6 6 0 0 0-10.2-4.3L5 10m1 2a6 6 0 0 0 10.2 4.3L19 14"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'menu'"
      d="M5 7h14M5 12h14M5 17h14"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
    />
    <template v-else-if="name === 'search'">
      <circle cx="10.5" cy="10.5" r="5.5" stroke="currentColor" stroke-width="1.7" />
      <path d="m15 15 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
    </template>
    <path
      v-else
      d="M12 3a9 9 0 1 0 9 9"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
    />
  </svg>
</template>
