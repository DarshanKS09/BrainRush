import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { PerfectPlayScreen } from './screens/PerfectPlay';
import { api } from './api';
import type { DashboardData, PerfectState } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      perfectState: vi.fn(),
      me: vi.fn(),
      start: vi.fn(),
      stopPerfect: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

function startedState(overrides: Partial<PerfectState> = {}): PerfectState {
  return {
    session_id: 'sid-1',
    game_type: 'perfect_second',
    difficulty: 'medium',
    target_ms: 5500,
    max_attempts: 1,
    attempts_used: 0,
    attempts_left: 1,
    status: 'started',
    finished: false,
    result: null,
    ...overrides,
  };
}

function dashboard(best: number | null): DashboardData {
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
    best_perfect_error_ms: best,
    rank: 1,
    active_games: [],
  };
}

let now = 1000;
beforeEach(() => {
  vi.useFakeTimers();
  now = 1000;
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  mockedApi.perfectState.mockResolvedValue(startedState());
  mockedApi.me.mockResolvedValue(dashboard(250));
  mockedApi.stopPerfect.mockResolvedValue(
    startedState({
      finished: true,
      status: 'completed',
      result: {
        outcome: 'win', score: 0, xp_earned: 100, secret: null,
        target_ms: 5500, actual_ms: 5500, error_ms: 0, accuracy_percent: 100,
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

async function renderReady() {
  render(<PerfectPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
  await act(async () => {});
  await act(async () => {});
}

describe('PerfectPlay', () => {
  it('shows the target before and during the attempt', async () => {
    await renderReady();
    // Target visible in header and hero, before START is pressed.
    expect(screen.getAllByText(/5.5 s/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('button', { name: /Start clock/ })).toBeInTheDocument();
    expect(screen.getByText(/Personal best error/)).toBeInTheDocument();
  });

  it('measures with the monotonic clock and submits once on double STOP', async () => {
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: /Start clock/ }));
    await act(async () => {});
    expect(screen.getByRole('button', { name: /STOP/ })).toBeInTheDocument();
    now += 5500;
    const stop = screen.getByRole('button', { name: /STOP/ });
    fireEvent.click(stop);
    fireEvent.click(stop); // double tap: second submit must be dropped
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.stopPerfect).toHaveBeenCalledTimes(1);
    expect(mockedApi.stopPerfect).toHaveBeenCalledWith('test', 'sid-1', 5500, expect.any(String));
    expect(screen.getByText('PERFECT! 🏆')).toBeInTheDocument();
    expect(screen.getByText('+100 XP', { exact: false })).toBeInTheDocument();
  });

  it('shows error details and a verdict for imperfect stops', async () => {
    mockedApi.stopPerfect.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: {
          outcome: 'loss', score: 3000, xp_earned: 70, secret: null,
          target_ms: 10000, actual_ms: 13000, error_ms: 3000, accuracy_percent: 70,
        },
      }),
    );
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: /Start clock/ }));
    await act(async () => {});
    now += 3000;
    fireEvent.click(screen.getByRole('button', { name: /STOP/ }));
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('Great timing! 🎯')).toBeInTheDocument();
    expect(screen.getByText('70.0%', { exact: false })).toBeInTheDocument();
  });

  it('replays with a fresh server-side target', async () => {
    const onReplay = vi.fn();
    cleanup();
    render(<PerfectPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={onReplay} />);
    await act(async () => {});
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Start clock/ }));
    await act(async () => {});
    now += 5500;
    fireEvent.click(screen.getByRole('button', { name: /STOP/ }));
    await act(async () => {});
    await act(async () => {});
    mockedApi.start.mockResolvedValue(startedState({ session_id: 'sid-2', target_ms: 7000 }));
    fireEvent.click(screen.getByRole('button', { name: /Play again/ }));
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.start).toHaveBeenCalledWith('test', 'perfect_second', 'medium');
    expect(onReplay).toHaveBeenCalledWith('sid-2');
  });

  it('space starts and stops the clock', async () => {
    await renderReady();
    fireEvent.keyDown(window, { key: ' ' });
    await act(async () => {});
    expect(screen.getByRole('button', { name: /STOP/ })).toBeInTheDocument();
    now += 1000;
    fireEvent.keyDown(window, { key: 'Enter' });
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.stopPerfect).toHaveBeenCalledTimes(1);
  });
});
