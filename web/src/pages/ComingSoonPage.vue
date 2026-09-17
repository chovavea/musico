<script setup lang="ts">
import AppIcon from "../components/AppIcon.vue";
import { comingSoon } from "../lib/coming-soon";

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    icon?: "compass" | "user" | "note";
    actions?: { label: string; soon?: string }[];
  }>(),
  {
    description: "这个功能即将上线。",
    icon: "compass",
    actions: () => [],
  },
);
</script>

<template>
  <section class="gz-soon">
    <div class="gz-soon-card gz-glass">
      <div class="gz-soon-mark">
        <AppIcon :name="icon" :size="24" />
      </div>
      <h1 data-page-heading tabindex="-1" class="outline-none">{{ title }}</h1>
      <p>{{ description }}</p>
      <p class="mb-4 text-xs tracking-[0.18em] text-[color:var(--gz-faint)]">COMING SOON</p>
      <div v-if="actions.length" class="gz-soon-list">
        <button
          v-for="action in actions"
          :key="action.label"
          type="button"
          class="gz-soon-item"
          @click="comingSoon(action.soon || action.label)"
        >
          <span>{{ action.label }}</span>
          <AppIcon name="chevron-right" :size="14" class="text-[color:var(--gz-faint)]" />
        </button>
      </div>
    </div>
  </section>
</template>
