<script setup lang="ts">
import ComingSoonPage from "./ComingSoonPage.vue";
</script>

<template>
  <ComingSoonPage
    title="发现"
    icon="compass"
    description="歌单广场、场景电台和个性化推荐会先在这里上线。"
    :actions="[
      { label: '每日推荐' },
      { label: '歌单广场' },
      { label: '新歌速递' },
      { label: '歌手墙' },
    ]"
  />
</template>
