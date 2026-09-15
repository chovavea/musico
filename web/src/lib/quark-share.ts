const SHARE_HOST = "pan.quark.cn";
const SHARE_PATH = /^\/s\/[A-Za-z0-9]+$/;

/** True when ``url`` is a Quark share page, not a look-alike on another host. */
export function isQuarkShareUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return false;
    if (parsed.username || parsed.password) return false;
    if (parsed.hostname.toLowerCase() !== SHARE_HOST) return false;
    if (parsed.port && parsed.port !== "443" && parsed.port !== "80") return false;
    return SHARE_PATH.test(parsed.pathname);
  } catch {
    return false;
  }
}
