import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import App from './App';
import { api, ApiError, type ReferralClaim } from './api';
import { initWebApp } from './telegram';

vi.mock('./telegram', () => ({ initWebApp: vi.fn(), haptic: vi.fn() }));

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      me: vi.fn(),
      history: vi.fn(),
      games: vi.fn(),
      start: vi.fn(),
      referralClaim: vi.fn(),
      referralMine: vi.fn(),
      referralStats: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const mockedInit = vi.mocked(initWebApp);

function telegramCtx(startParam: string | null = null) {
  return {
    initData: 'INIT-X',
    user: { id: 555 },
    displayName: 'Newbie',
    isTelegram: true,
    isDevMock: false,
    startParam,
  };
}

function dashboard() {
  return {
    user: { telegram_id: 555, username: 'n', display_name: 'Newbie' },
    profile: {
      level: 1, total_xp: 25, xp_into_level: 25, xp_for_next: 100,
      games_played: 0, wins: 0, losses: 0, current_streak: 0, longest_streak: 0,
    },
    today: { games_played: 0, xp_earned: 25 },
    best_win_attempts: null,
    best_color_level: null,
    best_reflex_score: null,
    rank: 1,
    active_games: [],
  };
}

beforeEach(() => {
  window.localStorage.clear();
  mockedInit.mockReturnValue(telegramCtx());
  mockedApi.me.mockResolvedValue(dashboard());
  mockedApi.history.mockResolvedValue({ items: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('referral claim gating (registration race)', () => {
  it('holds auto-registering screens until a pending claim settles', async () => {
    mockedInit.mockReturnValue(telegramCtx('CODE123'));
    let resolveClaim!: (v: ReferralClaim) => void;
    mockedApi.referralClaim.mockReturnValue(
      new Promise<ReferralClaim>((resolve) => { resolveClaim = resolve; }),
    );
    render(<App />);
    await act(async () => {});
    // Claim in flight: splash shown, dashboard (which registers) untouched.
    expect(screen.getByText(/Applying your invite/)).toBeInTheDocument();
    expect(mockedApi.referralClaim).toHaveBeenCalledWith('INIT-X', 'CODE123');
    expect(mockedApi.me).not.toHaveBeenCalled();
    await act(async () => {
      resolveClaim({ credited: true, already: false, code: 'CODE123', referrer_xp: 100, referred_xp: 25 });
    });
    await act(async () => {});
    expect(mockedApi.me).toHaveBeenCalled();
    expect(screen.getByText(/Welcome bonus: \+25 XP/)).toBeInTheDocument();
  });

  it('persists the pending code across reloads until credited', async () => {
    mockedInit.mockReturnValue(telegramCtx('SAVE-ME'));
    mockedApi.referralClaim.mockResolvedValue({
      credited: true, already: false, code: 'SAVE-ME', referrer_xp: 100, referred_xp: 25,
    });
    render(<App />);
    await act(async () => {});
    await act(async () => {});
    // Cleared after success; set during the pending window.
    expect(window.localStorage.getItem('brainrush:pendingReferral')).toBeNull();
  });

  it('shows ineligible state on 409 without private details and loads the app', async () => {
    mockedInit.mockReturnValue(telegramCtx('USEDCODE'));
    mockedApi.referralClaim.mockRejectedValue(new ApiError(409, 'referral already claimed or ineligible'));
    render(<App />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/not eligible for a bonus/)).toBeInTheDocument();
    expect(mockedApi.me).toHaveBeenCalled();
  });

  it('offers retry on network failure and keeps the token for a later attempt', async () => {
    mockedInit.mockReturnValue(telegramCtx('RETRYME'));
    mockedApi.referralClaim.mockRejectedValueOnce(new Error('offline'));
    render(<App />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/Couldn't verify your invite/)).toBeInTheDocument();
    expect(mockedApi.me).not.toHaveBeenCalled();
    mockedApi.referralClaim.mockResolvedValue({
      credited: true, already: false, code: 'RETRYME', referrer_xp: 100, referred_xp: 25,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.referralClaim).toHaveBeenCalledTimes(2);
    expect(mockedApi.me).toHaveBeenCalled();
  });

  it('skips gating entirely without a launch param and never claims', async () => {
    render(<App />);
    await act(async () => {});
    expect(mockedApi.referralClaim).not.toHaveBeenCalled();
    expect(mockedApi.me).toHaveBeenCalled();
  });
});
