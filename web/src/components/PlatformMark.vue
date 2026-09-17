<script setup lang="ts">
withDefaults(
  defineProps<{
    platform: string;
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
  >
    <template v-if="platform === 'qqmusic'">
      <circle cx="12" cy="13.4" r="7.4" fill="#111827" />
      <circle cx="8.6" cy="8.2" r="2.35" fill="#111827" />
      <circle cx="15.4" cy="8.2" r="2.35" fill="#111827" />
      <ellipse cx="12" cy="15.2" rx="4.8" ry="4.4" fill="#f8fafc" />
      <path d="M10.2 13.6c.55 1.35 3.05 1.35 3.6 0" fill="#f59e0b" />
      <circle cx="10.3" cy="12.3" r=".85" fill="#111827" />
      <circle cx="13.7" cy="12.3" r=".85" fill="#111827" />
    </template>
    <template v-else-if="platform === 'netease'">
      <rect width="24" height="24" rx="7" fill="#ef4444" />
      <path
        d="M8 15.2c0-3.4 2.2-5.4 4.6-5.4 1.4 0 2.4.7 2.4 1.8 0 2.4-3.4 2.2-3.4 4.1 0 .7.6 1.2 1.4 1.2 2.2 0 3.6-2.3 3.6-5.3"
        stroke="#fff"
        stroke-width="1.8"
        stroke-linecap="round"
      />
      <circle cx="14.8" cy="8.4" r="1.15" fill="#fff" />
    </template>
    <template v-else-if="platform === 'bilibili'">
      <rect x="3.2" y="6.4" width="17.6" height="12.4" rx="3.4" fill="#fb7299" />
      <path d="M8 6.4 6 3.6M16 6.4l2-2.8" stroke="#fb7299" stroke-width="1.8" stroke-linecap="round" />
      <rect x="7.1" y="10" width="3.2" height="3.6" rx="1" fill="#fff" />
      <rect x="13.7" y="10" width="3.2" height="3.6" rx="1" fill="#fff" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="9" fill="currentColor" opacity=".18" />
      <path
        d="M9 16V8l7-1.5V14"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </template>
  </svg>
</template>
