import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { api } from './api';
import type { DashboardData, GameState } from './api';
import { HomeScreen } from './screens/Home';
import type { WebAppContext } from './telegram';

/**
 * Regression coverage for the reported production issue:
 * "dashboard does not load correctly on the initial launch but appears
 * after the user completes a game and returns to the dashboard."
 *
 * First launch = HomeScreen's very first mount fires GET /api/me +
 * GET /api/history. If that burst fails (production: backend cold start),
 * the screen must show an actionable error — never latch on a spinner —
 * and a later mount (returning from a game) must load fresh and render.
 */

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
      matchJoinByToken: vi.fn(),
    },
  };
});

vi.mock('./telegram', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./telegram')>();
  return {
    ...actual,
    initWebApp: () => ({
      initData: 'test',
      user: null,
      displayName: 'Tess',
      isTelegram: true,
      isDevMock: false,
      startParam: null,
    }),
  };
});

vi.mock('./screens/Play', () => ({
  PlayScreen: ({ onExit }: { onExit: () => void }) => (
    <button onClick={onExit}>Exit game</button>
  ),
}));

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

function dashboard(): DashboardData {
  return {
    user: { telegram_id: 1, username: 't', display_name: 'Tess' },
    profile: {
      level: 3, total_xp: 250, xp_into_level: 50, xp_for_next: 100,
      games_played: 7, wins: 4, losses: 3, current_streak: 2, longest_streak: 5,
    },
    today: { games_played: 1, xp_earned: 40 },
    best_win_attempts: 2,
    best_color_level: null,
    best_reflex_score: null,
    rank: 12,
    active_games: [],
  };
}

beforeEach(() => {
  // [diag] console.debug instrumentation is intentionally silent in tests.
  vi.spyOn(console, 'debug').mockImplementation(() => {});
  mockedApi.history.mockResolvedValue({ items: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe('first-launch dashboard loading', () => {
  it('requests /me and /history on first mount and renders the dashboard', async () => {
    mockedApi.me.mockResolvedValue(dashboard());
    render(<HomeScreen ctx={ctx} onPlayNow={() => {}} onResume={() => {}} />);
    await act(async () => {});
    expect(mockedApi.me).toHaveBeenCalledTimes(1);
    expect(mockedApi.me).toHaveBeenCalledWith('test');
    expect(mockedApi.history).toHaveBeenCalledTimes(1);
    expect(mockedApi.history).toHaveBeenCalledWith('test', 5, 0);
    expect(await screen.findByText('Welcome back to BrainRush')).toBeInTheDocument();
    expect(screen.queryByRole('status')).toBeNull(); // loading finished
  });

  it('shows an actionable error (not an infinite spinner) when the first burst fails', async () => {
    mockedApi.me.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    mockedApi.me.mockResolvedValue(dashboard());
    render(<HomeScreen ctx={ctx} onPlayNow={() => {}} onResume={() => {}} />);
    await act(async () => {});
    // Loading cleared — never stuck on "Loading your arcade…".
    expect(screen.queryByText('Loading your arcade…')).toBeNull();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Failed to fetch');
    // Recovery is available and performs a fresh load.
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await act(async () => {});
    expect(await screen.findByText('Welcome back to BrainRush')).toBeInTheDocument();
    expect(mockedApi.me).toHaveBeenCalledTimes(2);
  });
});

describe('returning from a game reloads the dashboard', () => {
  it('first launch fails, a game session works, Home tab then shows the dashboard', async () => {
    // First /me call fails (production cold-start burst); later ones succeed.
    mockedApi.me
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue(dashboard());
    mockedApi.games.mockResolvedValue({
      games: [
        {
          id: 'number_guessing', title: 'Number Guessing', description: 'Guess it.',
          playable: true, difficulties: [{ id: 'medium', max_attempts: 10 }],
          multiplayer: null,
        },
      ],
    });
    mockedApi.start.mockResolvedValue({
      session_id: 'sid-1', game_type: 'number_guessing', difficulty: 'medium',
      max_attempts: 10, attempts_used: 0, attempts_left: 10, guesses: [],
      status: 'started', finished: false, result: null,
    } as GameState);

    const { default: App } = await import('./App');

    // 1. Initial launch: dashboard burst fails -> visible error, not a spinner.
    render(<App />);
    await act(async () => {});
    await act(async () => {});
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch');
    expect(screen.queryByText('Loading your arcade…')).toBeNull();
    expect(mockedApi.me).toHaveBeenCalledTimes(1);

    // 2. Play a game: Games tab -> tile -> Play Now -> in-game -> exit.
    fireEvent.click(screen.getByRole('button', { name: /Games/ }));
    await act(async () => {});
    fireEvent.click(await screen.findByRole('button', { name: 'Number Guessing' }));
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Play Now' }));
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Exit game' }));
    await act(async () => {});
    expect(mockedApi.me).toHaveBeenCalledTimes(1); // games flow doesn't touch /me

    // 3. Return to Home: a FRESH mount issues a fresh load -> dashboard shows.
    fireEvent.click(screen.getByRole('button', { name: /Home/ }));
    await act(async () => {});
    expect(await screen.findByText('Welcome back to BrainRush')).toBeInTheDocument();
    expect(mockedApi.me).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Lv 3')).toBeInTheDocument();
  });
});
