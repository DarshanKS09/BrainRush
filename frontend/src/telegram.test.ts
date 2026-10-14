import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { initWebApp } from './telegram';

function mockWebApp(overrides: Record<string, unknown> = {}) {
  (window as unknown as { Telegram?: unknown }).Telegram = {
    WebApp: {
      initData: 'INIT-DATA',
      initDataUnsafe: {},
      ready: vi.fn(),
      expand: vi.fn(),
      ...overrides,
    },
  };
}

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

afterEach(() => {
  delete (window as unknown as { Telegram?: unknown }).Telegram;
  window.history.replaceState({}, '', '/');
  vi.unstubAllGlobals();
});

describe('referral start_param capture', () => {
  it('captures start_param from Telegram launch context without manual entry', () => {
    mockWebApp({ initDataUnsafe: { start_param: 'AB12CD34EF' } });
    const ctx = initWebApp();
    expect(ctx.startParam).toBe('AB12CD34EF');
    expect(ctx.initData).toBe('INIT-DATA');
  });

  it('falls back to tgWebAppStartParam URL query when unsafe context lacks it', () => {
    mockWebApp({ initDataUnsafe: {} });
    window.history.replaceState({}, '', '/?tgWebAppStartParam=URLCODE99');
    expect(initWebApp().startParam).toBe('URLCODE99');
  });

  it('falls back to startapp URL query', () => {
    mockWebApp({ initDataUnsafe: {} });
    window.history.replaceState({}, '', '/?startapp=STARTAPP1');
    expect(initWebApp().startParam).toBe('STARTAPP1');
  });

  it('prefers the Telegram context over the URL query', () => {
    mockWebApp({ initDataUnsafe: { start_param: 'CTXCODE' } });
    window.history.replaceState({}, '', '/?startapp=URLCODE');
    expect(initWebApp().startParam).toBe('CTXCODE');
  });

  it('rejects malformed params instead of passing them to the backend', () => {
    mockWebApp({ initDataUnsafe: { start_param: 'bad code!!' } });
    expect(initWebApp().startParam).toBeNull();
    window.history.replaceState({}, '', '/?startapp=' + encodeURIComponent('a'.repeat(65)));
    mockWebApp({ initDataUnsafe: {} });
    expect(initWebApp().startParam).toBeNull();
  });

  it('returns null outside Telegram with no param', () => {
    const ctx = initWebApp();
    expect(ctx.startParam).toBeNull();
    expect(ctx.initData).toBe('');
  });
});
