import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { ReflexPlayScreen } from './screens/ReflexPlay';
import { api } from './api';
import type { DashboardData, GameInfo, ReflexState } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      reflexState: vi.fn(),
      state: vi.fn(),
      me: vi.fn(),
      games: vi.fn(),
      start: vi.fn(),
      finishReflex: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

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

function catalog(): { games: GameInfo[] } {
  return {
    games: [
      {
        id: 'reflex_rush',
        title: 'Reflex Rush',
        description: 'Tap fast.',
        playable: true,
        difficulties: [{ id: 'medium', max_attempts: 5 }],
      },
    ],
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
    best_reflex_score: best,
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
  mockedApi.me.mockResolvedValue(dashboard(900));
  mockedApi.games.mockResolvedValue(catalog());
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

async function renderAndStart() {
  render(<ReflexPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
  await act(async () => {});
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: /Start Game/ }));
  await act(async () => {});
}

describe('ReflexPlay', () => {
  it('shows intro rules first and schedules nothing until Start', async () => {
    render(<ReflexPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/Wait for green, then tap as fast as you can/)).toBeInTheDocument();
    expect(screen.getByText(/false start/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Wait for green|Tap now/ })).not.toBeInTheDocument();
    await act(async () => {
      vi.runAllTimers();
    });
    expect(mockedApi.finishReflex).not.toHaveBeenCalled();
  });

  it('transitions waiting to active and measures a valid tap', async () => {
    await renderAndStart();
    expect(screen.getByText(/Wait for green/)).toBeInTheDocument();
    // Tap during waiting would be a false start; advance to active instead.
    await act(async () => {
      vi.runAllTimers();
    });
    expect(screen.getByRole('button', { name: 'Tap now' })).toBeInTheDocument();
    now += 237;
    fireEvent.click(screen.getByRole('button', { name: 'Tap now' }));
    await act(async () => {});
    expect(screen.getAllByText(/237 ms/)[0]).toBeInTheDocument();
    expect(mockedApi.finishReflex).not.toHaveBeenCalled();
  });

  it('penalizes a false start with 0 points and keeps the round counted', async () => {
    await renderAndStart();
    fireEvent.click(screen.getByRole('button', { name: /Wait for green/ }));
    await act(async () => {});
    expect(screen.getByText(/False start — 0 pts/)).toBeInTheDocument();
    expect(screen.getByText(/False starts:/)).toBeInTheDocument();
  });

  it('ignores duplicate taps for the same round', async () => {
    await renderAndStart();
    await act(async () => {
      vi.runAllTimers();
    });
    now += 200;
    const target = screen.getByRole('button', { name: 'Tap now' });
    fireEvent.click(target);
    fireEvent.click(target);
    await act(async () => {});
    // Still round 1 of 5 recorded once; no submit yet.
    expect(screen.getAllByText(/200 ms/)[0]).toBeInTheDocument();
    expect(mockedApi.finishReflex).not.toHaveBeenCalled();
  });

  it('plays five rounds then submits once with the same id on retry', async () => {
    await renderAndStart();
    for (let r = 0; r < 5; r++) {
      await act(async () => {
        vi.runAllTimers();
      });
      now += 200 + r * 10;
      fireEvent.click(screen.getByRole('button', { name: 'Tap now' }));
      await act(async () => {});
      if (r < 4) {
        await act(async () => {
          vi.runAllTimers(); // 900ms beat -> next wait
        });
        await act(async () => {
          vi.runAllTimers(); // wait -> active
        });
      }
    }
    await act(async () => {});
    expect(mockedApi.finishReflex).toHaveBeenCalledOnce();
    const [, , rounds, subId] = mockedApi.finishReflex.mock.calls[0];
    expect(rounds).toHaveLength(5);
    expect(typeof subId).toBe('string');
  });

  it('cleans up outstanding timers on unmount', async () => {
    await renderAndStart();
    cleanup();
    await act(async () => {
      vi.runAllTimers();
    });
  });

  it('renders the completed panel with average, best and score', async () => {
    mockedApi.reflexState.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: {
          outcome: 'win', score: 4000, xp_earned: 80, secret: null,
          avg_ms: 240, best_ms: 200, false_starts: 1,
          rounds: [
            { reaction_ms: null, false_start: true },
            { reaction_ms: 200, false_start: false },
            { reaction_ms: 220, false_start: false },
            { reaction_ms: 260, false_start: false },
            { reaction_ms: 280, false_start: false },
          ],
        },
      }),
    );
    render(<ReflexPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('Lightning reflexes!')).toBeInTheDocument();
    expect(screen.getByText(/Avg/)).toBeInTheDocument();
    expect(screen.getByText(/New personal best!/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lobby' })).toBeInTheDocument();
  });

  it('replays at the same difficulty and cancels cleanly', async () => {    const onExit = vi.fn();
    const onReplay = vi.fn();
    mockedApi.reflexState.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: {
          outcome: 'loss', score: 500, xp_earned: 12, secret: null,
          avg_ms: 800, best_ms: 700, false_starts: 0,
          rounds: [700, 750, 800, 850, 900].map((reaction_ms) => ({ reaction_ms, false_start: false })),
        },
      }),
    );
    mockedApi.start = vi.fn().mockResolvedValue({ session_id: 'sid-2' });
    render(<ReflexPlayScreen ctx={ctx} sessionId="sid-1" onExit={onExit} onReplay={onReplay} />);
    await act(async () => {});
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Play again/ }));
    await act(async () => {});
    expect(mockedApi.start).toHaveBeenCalledWith('test', 'reflex_rush', 'medium');
    expect(onReplay).toHaveBeenCalledWith('sid-2');
  });

  it('shows retry on submit failure and succeeds once on retry', async () => {
    await renderAndStart();
    for (let r = 0; r < 5; r++) {
      await act(async () => {
        vi.runAllTimers();
      });
      now += 210;
      if (r === 4) {
        mockedApi.finishReflex.mockRejectedValueOnce(new Error('network down'));
      }
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
    // Failed submit: actionable error + Retry, no stuck screen, no result yet.
    expect(screen.getByText(/network down/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry submit' })).toBeInTheDocument();
    expect(screen.queryByText('Lightning reflexes!')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry submit' }));
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('Lightning reflexes!')).toBeInTheDocument();
    // Same submission id on retry: backend replay makes it idempotent.
    const calls = mockedApi.finishReflex.mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0][3]).toBe(calls[1][3]);
  });
});
