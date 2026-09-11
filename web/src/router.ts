import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 };
  },
  routes: [
    { path: "/", name: "overview", component: () => import("./pages/OverviewPage.vue"), meta: { title: "总览" } },
    { path: "/boards", name: "boards", component: () => import("./pages/BoardsPage.vue"), meta: { title: "榜单管理" } },
    {
      path: "/charts/:board",
      name: "chart",
      component: () => import("./pages/ChartPage.vue"),
      props: true,
      meta: { title: "榜单" },
    },
    { path: "/health", name: "health", component: () => import("./pages/HealthPage.vue"), meta: { title: "源状态" } },
    { path: "/library", name: "library", component: () => import("./pages/LibraryPage.vue"), meta: { title: "音乐库" } },
    { path: "/search", name: "search", component: () => import("./pages/SearchPage.vue"), meta: { title: "搜索" } },
    { path: "/:pathMatch(.*)*", name: "not-found", component: () => import("./pages/NotFoundPage.vue"), meta: { title: "页面不存在" } },
  ],
});

router.afterEach((to) => {
  const title = typeof to.meta.title === "string" ? to.meta.title : "Musico";
  document.title = title === "Musico" ? title : `${title} · Musico`;
  window.requestAnimationFrame(() => {
    document.querySelector<HTMLElement>("[data-page-heading]")?.focus({ preventScroll: true });
  });
});
