<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import AppIcon from "../components/AppIcon.vue";
import ComingSoonToast from "../components/ComingSoonToast.vue";
import PageStage from "../components/PageStage.vue";
import PlayerBar from "../components/PlayerBar.vue";
import SettingsMenu from "../components/SettingsMenu.vue";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";

const route = useRoute();
const router = useRouter();
const player = usePlayerStore();
const theme = useThemeStore();

const tagline = computed(() =>
  theme.dark ? "音乐 · 让生活更有节奏" : "让音乐更有温度",
);

const tabs = [
  { to: "/", name: "overview", label: "首页", icon: "home" },
  { to: "/discover", name: "discover", label: "发现", icon: "compass" },
  { to: "/library", name: "library", label: "我的音乐", icon: "note" },
  { to: "/profile", name: "profile", label: "个人中心", icon: "user" },
] as const;

function onHeaderSearch() {
  if (route.name === "overview") {
    document.getElementById("gz-search")?.focus();
    return;
  }
  void router.push({ name: "search" });
}

function tabClass(active: boolean): string {
  return active ? "is-on" : "";
}
</script>

<template>
  <div class="gz-app">
    <div class="gz-ambient" aria-hidden="true" />
    <a
      href="#main-content"
      class="sr-only fixed left-4 top-4 z-[110] rounded-lg bg-white px-4 py-3 text-zinc-900 focus:not-sr-only"
    >
      跳到主要内容
    </a>
    <div class="gz-frame">
      <header class="gz-top">
        <RouterLink to="/" class="gz-brand" aria-label="Musico 首页">
          <span class="gz-logo">m</span>
          <span class="gz-brand-text">
            <span class="gz-name">musico</span>
            <span class="gz-tagline">{{ tagline }}</span>
          </span>
        </RouterLink>
        <nav class="gz-nav-desktop" aria-label="主要导航">
          <RouterLink
            v-for="tab in tabs"
            :key="tab.name"
            :to="tab.to"
            :class="tabClass(route.name === tab.name)"
          >
            {{ tab.label }}
          </RouterLink>
        </nav>
        <div class="gz-top-actions">
          <button
            type="button"
            class="gz-icon-btn"
            aria-label="搜索"
            @click="onHeaderSearch"
          >
            <AppIcon name="search" :size="18" />
          </button>
          <SettingsMenu variant="avatar" />
        </div>
      </header>
      <main
        id="main-content"
        class="gz-main page-stage"
        :class="player.current ? 'has-player' : 'no-player'"
      >
        <PageStage />
      </main>
    </div>
    <PlayerBar v-if="player.current" />
    <nav class="gz-tabbar" aria-label="底部导航">
      <RouterLink
        v-for="tab in tabs"
        :key="tab.name"
        :to="tab.to"
        :class="tabClass(route.name === tab.name)"
      >
        <AppIcon :name="tab.icon" :size="20" />
        <span>{{ tab.label }}</span>
      </RouterLink>
    </nav>
    <ComingSoonToast />
  </div>
</template>
