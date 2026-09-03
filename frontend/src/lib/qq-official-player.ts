export const QQ_PLAYER_SCRIPT =
  "https://y.gtimg.cn/music/h5/player/player.js?max_age=2592000";

export type QQOfficialEvent = {
  type?: string;
  currentTime?: number;
  message?: string;
  page?: string;
  code?: number;
};

export type QQOfficialPlayer = {
  play: (songs?: string | string[] | null, opts?: { index?: number; target?: string }) => QQOfficialPlayer;
  pause: (target?: string) => QQOfficialPlayer;
  toggle: (force?: boolean) => QQOfficialPlayer;
  playReady: () => QQOfficialPlayer;
  on: (event: string, handler: (event: QQOfficialEvent) => void) => QQOfficialPlayer;
  off: (event: string, handler?: (event: QQOfficialEvent) => void) => QQOfficialPlayer;
  currentTime: number;
  duration: number;
  data: { song?: { mid?: string; name?: string } };
};

type PlayerCtor = new (opts?: { target?: string; loop?: boolean; filter?: boolean }) => QQOfficialPlayer;

declare global {
  interface Window {
    Player?: PlayerCtor;
    QMplayer?: PlayerCtor;
  }
}

let instance: QQOfficialPlayer | null = null;
let loading: Promise<QQOfficialPlayer> | null = null;

function createInstance(): QQOfficialPlayer {
  const Ctor = window.QMplayer ?? window.Player;
  if (!Ctor) {
    throw new Error("QMplayer unavailable");
  }
  return new Ctor({ target: "web", loop: false, filter: false });
}

export function getQQOfficialPlayer(): QQOfficialPlayer | null {
  return instance;
}

export function loadQQOfficialPlayer(): Promise<QQOfficialPlayer> {
  if (instance) {
    return Promise.resolve(instance);
  }
  if (loading) {
    return loading;
  }
  loading = new Promise((resolve, reject) => {
    try {
      instance = createInstance();
      resolve(instance);
      return;
    } catch {
      /* script not loaded yet */
    }
    const script = document.createElement("script");
    script.src = QQ_PLAYER_SCRIPT;
    script.async = true;
    script.onload = () => {
      try {
        instance = createInstance();
        resolve(instance);
      } catch (error) {
        loading = null;
        reject(error);
      }
    };
    script.onerror = () => {
      loading = null;
      reject(new Error("QMplayer script failed"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

export function pauseQQOfficialPlayer(): void {
  instance?.pause("web");
}
