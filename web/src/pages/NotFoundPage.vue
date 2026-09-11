<script setup lang="ts">
import { RouterLink } from "vue-router";
import PageHeader from "../components/PageHeader.vue";
</script>

<template>
  <section class="py-8">
    <PageHeader
      title="找不到这个页面"
      eyebrow="404"
      description="链接可能已失效，或页面已经移动。"
    />
    <RouterLink
      to="/"
      class="inline-flex h-11 items-center rounded-full bg-zinc-900 px-5 text-sm font-medium text-white dark:bg-white dark:text-zinc-900"
    >
      返回总览
    </RouterLink>
  </section>
</template>
