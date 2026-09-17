<script setup lang="ts">
import ComingSoonPage from "./ComingSoonPage.vue";
</script>

<template>
  <ComingSoonPage
    title="个人中心"
    icon="user"
    description="账号、收藏和听歌偏好会放在这里，现在可以先用右上角配置。"
    :actions="[
      { label: '最近播放' },
      { label: '我的收藏' },
      { label: '已购与会员' },
      { label: '通知与隐私' },
    ]"
  />
</template>
