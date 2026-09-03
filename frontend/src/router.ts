import { createRouter, createWebHistory } from "vue-router";
import OverviewPage from "./pages/OverviewPage.vue";
import BoardsPage from "./pages/BoardsPage.vue";
import ChartPage from "./pages/ChartPage.vue";
import HealthPage from "./pages/HealthPage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "overview", component: OverviewPage },
    { path: "/boards", name: "boards", component: BoardsPage },
    { path: "/charts/:board", name: "chart", component: ChartPage, props: true },
    { path: "/health", name: "health", component: HealthPage },
  ],
});
