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

  it('starts any playable game by id', async () => {
    const fetch = mockFetch(200, { session_id: 's1' });
    await api.start('data', 'color_sequence', 'easy');
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/sessions')).toBe(true);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      game_type: 'color_sequence',
      difficulty: 'easy',
    });
  });

  it('posts color moves with client id', async () => {
    const fetch = mockFetch(200, { finished: false });
    await api.move('data', 'sid-1', 2, 'm-7');
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/sessions/sid-1/move')).toBe(true);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ color: 2, client_move_id: 'm-7' });
  });

  it('fetches referral link and stats', async () => {
    const fetch = mockFetch(200, { code: 'AB12CD34EF', link: 'https://t.me/x', referrer_xp: 100, referred_xp: 25 });
    const mine = await api.referralMine('data');
    expect(mine.code).toBe('AB12CD34EF');
    const [url] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/referrals/mine')).toBe(true);
  });

  it('claims referrals with code only (no user ids)', async () => {
    const fetch = mockFetch(200, { credited: true, already: false, code: 'AB12CD34EF', referrer_xp: 100, referred_xp: 25 });
    const out = await api.referralClaim('data', 'AB12CD34EF');
    expect(out.credited).toBe(true);
    const [, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ code: 'AB12CD34EF' });
  });

  it('passes an abort signal for the reflex submit timeout', async () => {
    const fetch = mockFetch(200, { finished: true });
    await api.finishReflex('data', 'sid-1', [], 'sub-1');
    const [, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('surfaces aborted requests as errors', async () => {
    const fetch = vi.fn().mockRejectedValue(new DOMException('timed out', 'AbortError'));
    vi.stubGlobal('fetch', fetch);
    await expect(
      api.finishReflex('data', 'sid-1', [], 'sub-1'),
    ).rejects.toThrow();
  });
});
