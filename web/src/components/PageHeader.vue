<script setup lang="ts">
import { RouterLink } from "vue-router";
import AppIcon from "./AppIcon.vue";

withDefaults(
  defineProps<{
    title: string;
    eyebrow?: string;
    description?: string;
    backTo?: string;
    backLabel?: string;
  }>(),
  {
    eyebrow: "",
    description: "",
    backTo: "",
    backLabel: "返回",
  },
);
</script>

<template>
  <header class="mb-6">
    <RouterLink
      v-if="backTo"
      :to="backTo"
      class="mb-3 inline-flex min-h-11 items-center gap-1 text-sm text-secondary transition hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <AppIcon name="chevron-left" :size="18" />
      {{ backLabel }}
    </RouterLink>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p v-if="eyebrow" class="text-sm text-tertiary">{{ eyebrow }}</p>
        <h1
          data-page-heading
          tabindex="-1"
          class="mt-1 text-2xl font-semibold tracking-tight outline-none md:text-3xl"
        >
          {{ title }}
        </h1>
        <p v-if="description" class="mt-2 max-w-2xl text-sm text-secondary">
          {{ description }}
        </p>
        <slot name="meta" />
      </div>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
