import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "overview", component: () => import("./pages/OverviewPage.vue") },
    { path: "/boards", name: "boards", component: () => import("./pages/BoardsPage.vue") },
    {
      path: "/charts/:board",
      name: "chart",
      component: () => import("./pages/ChartPage.vue"),
      props: true,
    },
    { path: "/health", name: "health", component: () => import("./pages/HealthPage.vue") },
    { path: "/library", name: "library", component: () => import("./pages/LibraryPage.vue") },
    { path: "/search", name: "search", component: () => import("./pages/SearchPage.vue") },
  ],
});
