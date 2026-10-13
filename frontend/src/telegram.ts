/** Telegram WebApp SDK bridge. No secrets handled here (initData is auth input). */

export interface TelegramUser {
  id: number;
  username?: string;
  first_name?: string;
  last_name?: string;
}

export interface WebAppContext {
  /** Raw initData string to send as X-Telegram-Init-Data. Empty outside Telegram. */
  initData: string;
  user: TelegramUser | null;
  displayName: string;
  isTelegram: boolean;
  /** Development mock flag: true only for local DEV builds with ?devuser=. */
  isDevMock: boolean;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        initDataUnsafe?: { user?: TelegramUser };
        colorScheme?: string;
        ready: () => void;
        expand: () => void;
        HapticFeedback?: {
          impactOccurred: (style: string) => void;
          notificationOccurred: (type: string) => void;
        };
      };
    };
  }
}

function devMockUser(): TelegramUser | null {
  // Explicit local-dev escape hatch: only honored in DEV builds, never in
  // production (import.meta.env.DEV is false in `vite build` output).
  if (!import.meta.env.DEV) return null;
  const params = new URLSearchParams(window.location.search);
  if (!params.has('devuser')) return null;
  return { id: 9001, username: 'devplayer', first_name: 'Dev' };
}

export function initWebApp(): WebAppContext {
  const wa = window.Telegram?.WebApp;
  const mock = devMockUser();
  if (mock) {
    return {
      initData: 'dev',
      user: mock,
      displayName: 'Dev Player',
      isTelegram: false,
      isDevMock: true,
    };
  }
  if (!wa) {
    return { initData: '', user: null, displayName: 'Guest', isTelegram: false, isDevMock: false };
  }
  try {
    wa.ready();
    wa.expand();
  } catch {
    /* older clients: non-fatal */
  }
  const user = wa.initDataUnsafe?.user ?? null;
  const displayName =
    [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || 'Player';
  return { initData: wa.initData || '', user, displayName, isTelegram: true, isDevMock: false };
}

export function haptic(kind: 'light' | 'success' | 'error' = 'light'): void {
  try {
    const hf = window.Telegram?.WebApp?.HapticFeedback;
    if (!hf) return;
    if (kind === 'success' || kind === 'error') hf.notificationOccurred(kind);
    else hf.impactOccurred('light');
  } catch {
    /* non-Telegram browsers: silent */
  }
}
