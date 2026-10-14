import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { api } from './api';
import type { ReflexState } from './api';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      reflexState: vi.fn(),
      me: vi.fn(),
      games: vi.fn(),
      start: vi.fn(),
      finishReflex: vi.fn(),
      cancel: vi.fn(),
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
      displayName: 'T',
      isTelegram: true,
      isDevMock: false,
      startParam: null,
    }),
  };
});
vi.mock('./screens/Home', () => ({
  HomeScreen: ({ onPlayNow }: { onPlayNow: () => void }) => (
    <button onClick={onPlayNow}>go-games</button>
  ),
}));
vi.mock('./screens/Games', () => ({
  GamesScreen: ({ onStart }: { onStart: (gameId: string, sessionId: string) => void }) => (
    <button onClick={() => onStart('reflex_rush', 'sid-1')}>start-game</button>
  ),
}));
vi.mock('./screens/Leaderboard', () => ({
  LeaderboardScreen: () => null,
}));
vi.mock('./screens/Profile', () => ({
  ProfileScreen: () => null,
}));
vi.mock('./screens/Play', () => ({
  PlayScreen: () => null,
}));
vi.mock('./screens/ColorPlay', () => ({
  ColorPlayScreen: () => null,
}));

import App from './App';

const mockedApi = vi.mocked(api, true);

function startedState(overrides: Partial<ReflexState> = {}): ReflexState {
  return {
    session_id: 'sid-1',
    game_type: 'reflex_rush',
    difficulty: 'medium',
    max_attempts: 5,
    rounds_total: 5,
    rounds_played: 0,
    guesses: [],
    status: 'started',
    finished: false,
    result: null,
    ...overrides,
  };
}

function dashboard(): import('./api').DashboardData {
  return {
    user: { telegram_id: 1, username: 't', display_name: 'T' },
    profile: {
      level: 1, total_xp: 0, xp_into_level: 0, xp_for_next: 100,
      games_played: 0, wins: 0, losses: 0, current_streak: 0, longest_streak: 0,
    },
    today: { games_played: 0, xp_earned: 0 },
    best_win_attempts: null,
    best_color_level: null,
    best_reflex_score: null,
    rank: 1,
    active_games: [],
  };
}

let now = 1000;

beforeEach(() => {
  vi.useFakeTimers();
  now = 1000;
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  mockedApi.reflexState.mockResolvedValue(startedState());
  mockedApi.me.mockResolvedValue(dashboard());
  mockedApi.games.mockResolvedValue({ games: [] });
  mockedApi.start.mockResolvedValue(
    startedState({ session_id: 'sid-2' }),
  );
  mockedApi.finishReflex.mockResolvedValue(
    startedState({
      finished: true,
      status: 'completed',
      result: {
        outcome: 'win', score: 4000, xp_earned: 80, secret: null,
        avg_ms: 240, best_ms: 200, false_starts: 0,
        rounds: [200, 220, 240, 260, 280].map((reaction_ms) => ({ reaction_ms, false_start: false })),
      },
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe('App play routing', () => {
  it('remounts the reflex screen for a fresh session on replay', async () => {
    render(<App />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'go-games' }));
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'start-game' }));
    await act(async () => {});
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Start Game/ }));
    await act(async () => {});

    // Play all five rounds through the real screen.
    for (let r = 0; r < 5; r++) {
      await act(async () => {
        vi.runAllTimers();
      });
      now += 210;
      fireEvent.click(screen.getByRole('button', { name: 'Tap now' }));
      await act(async () => {});
      if (r < 4) {
        await act(async () => {
          vi.runAllTimers();
        });
        await act(async () => {
          vi.runAllTimers();
        });
      }
    }
    await act(async () => {});
    expect(screen.getByText('Lightning reflexes!')).toBeInTheDocument();

    // Play Again must open a FRESH game: instructions return, no stale
    // 5/5 progress, no stuck submitting banner, submission guard reset.
    fireEvent.click(screen.getByRole('button', { name: /Play again/ }));
    await act(async () => {});
    await act(async () => {});
    expect(
      screen.getByText(/Wait for green, then tap as fast as you can/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Submitting your time/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start Game/ })).toBeInTheDocument();
  });
});
