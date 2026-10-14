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

describe('reflex api client', () => {
  it('posts five rounds with a submission id', async () => {
    const fetch = mockFetch(200, { finished: true });
    const rounds = [200, 220, 240, 260, 280].map((reaction_ms) => ({ reaction_ms, false_start: false }));
    await api.finishReflex('data', 'sid-1', rounds, 'sub-1');
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/sessions/sid-1/finish')).toBe(true);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ rounds, client_submission_id: 'sub-1' });
  });

  it('loads reflex state', async () => {
    const fetch = mockFetch(200, { finished: false });
    await api.reflexState('d', 'sid-9');
    const [url] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith('/api/sessions/sid-9')).toBe(true);
  });
});
