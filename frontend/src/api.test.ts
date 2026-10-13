import { describe, expect, it, vi, afterEach } from 'vitest';
import { ApiError, api, buildUrl, newClientGuessId } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockFetch(status: number, body: unknown) {
  const fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('api client', () => {
  it('sends initData header and parses dashboard', async () => {
    const fetch = mockFetch(200, { profile: { level: 2 } });
    const me = await api.me('INIT-DATA-123');
    expect(me.profile.level).toBe(2);
    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
    expect(url).toBe('/api/me');
    expect(init.headers['X-Telegram-Init-Data']).toBe('INIT-DATA-123');
  });

  it('posts guess payload with client id', async () => {
    const fetch = mockFetch(200, { finished: false });
    await api.guess('data', 'sid-1', 42, 'cid-9');
    const [, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ value: 42, client_guess_id: 'cid-9' });
  });

  it('maps server detail messages into ApiError', async () => {
    mockFetch(404, { detail: 'gone' });
    await expect(api.state('d', 'sid')).rejects.toMatchObject({ status: 404, message: 'gone' } as unknown as ApiError);
  });

  it('buildUrl respects empty base (same origin)', () => {
    expect(buildUrl('/api/me')).toBe('/api/me');
  });

  it('generates unique client guess ids', () => {
    expect(newClientGuessId()).not.toBe(newClientGuessId());
  });
});
