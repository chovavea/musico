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
      | "spinner"
      | "home"
      | "compass"
      | "note"
      | "user"
      | "shuffle"
      | "waveform"
      | "queue"
      | "play-outline";
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
      v-else-if="name === 'home'"
      d="M4.5 11 12 4.5 19.5 11v8a1.5 1.5 0 0 1-1.5 1.5h-4v-5h-4v5H6A1.5 1.5 0 0 1 4.5 19v-8Z"
      fill="currentColor"
    />
    <template v-else-if="name === 'compass'">
      <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.7" />
      <path d="m14.8 9.2-1.2 4.4-4.4 1.2 1.2-4.4 4.4-1.2Z" fill="currentColor" />
    </template>
    <path
      v-else-if="name === 'note'"
      d="M9 18V7.2L19 5v10.2M9 18a2.6 2.6 0 1 1-2.6-2.6H9V18Zm10-2.8a2.6 2.6 0 1 1-2.6-2.6H19v2.6Z"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <template v-else-if="name === 'user'">
      <circle cx="12" cy="8.2" r="3.2" stroke="currentColor" stroke-width="1.7" />
      <path
        d="M6 19.2c.7-3.1 3-4.7 6-4.7s5.3 1.6 6 4.7"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
      />
    </template>
    <path
      v-else-if="name === 'shuffle'"
      d="M16 5h4v4M20 5l-6.5 6.5M8.5 8.5 4 13m12 6h4v-4M20 19l-5-5"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      v-else-if="name === 'waveform'"
      d="M4 10v4M8 7v10M12 5v14M16 8v8M20 10v4"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
    />
    <path
      v-else-if="name === 'queue'"
      d="M7 7h13M7 12h13M7 17h9M4 7h.01M4 12h.01M4 17h.01"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
    />
    <template v-else-if="name === 'play-outline'">
      <circle cx="12" cy="12" r="8.2" stroke="currentColor" stroke-width="1.5" />
      <path d="m10 8.8 6 3.2-6 3.2V8.8Z" fill="currentColor" />
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
