import { describe, expect, it, vi, afterEach } from 'vitest';
import { api } from './api';

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

describe('match room-code client', () => {
  it('posts the code to join-by-code', async () => {
    const fetch = mockFetch(200, { match_id: 'm1', room_code: 'ABC123' });
    const view = await api.matchJoinByCode('data', 'ABC123');
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/matches/join-by-code')).toBe(true);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ code: 'ABC123' });
    expect(view.room_code).toBe('ABC123');
  });
});
