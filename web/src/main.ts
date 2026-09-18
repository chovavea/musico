import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { syncApiTokenCookie } from "./api";
import { router } from "./router";
import { useThemeStore } from "./stores/theme";
import "./style.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
useThemeStore().init();
// 令牌存在 localStorage 里，Cookie 是会话级的：每次打开应用补一次，否则重启
// 浏览器后曲库试听/下载（媒体地址带不了请求头）会因为没有令牌而 401。
syncApiTokenCookie();
app.mount("#app");
