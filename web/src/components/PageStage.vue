<script setup lang="ts">
import { RouterView, useRoute } from "vue-router";

const route = useRoute();
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page">
      <component :is="Component" v-if="Component" :key="route.path" />
    </Transition>
  </RouterView>
</template>
