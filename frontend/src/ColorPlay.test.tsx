import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { ColorPlayScreen } from './screens/ColorPlay';
import { api } from './api';
import type { ColorState, DashboardData, GameInfo } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      state: vi.fn(),
      colorState: vi.fn(),
      me: vi.fn(),
      games: vi.fn(),
      start: vi.fn(),
      move: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);

const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

function startedState(overrides: Partial<ColorState> = {}): ColorState {
  return {
    session_id: 'sid-1',
    game_type: 'color_sequence',
    difficulty: 'easy',
    max_attempts: 8,
    display: [0, 2],
    position: 0,
    level: 2,
    max_level: 8,
    levels_completed: 0,
    moves: [],
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
        id: 'color_sequence',
        title: 'Color Sequence',
        description: 'Repeat the sequence.',
        playable: true,
        difficulties: [{ id: 'easy', max_attempts: 8, start_length: 3, playback_ms: 50 }],
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
    best_color_level: best,
    rank: 1,
    active_games: [],
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  mockedApi.colorState.mockResolvedValue(startedState());
  mockedApi.me.mockResolvedValue(dashboard(5));
  mockedApi.games.mockResolvedValue(catalog());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

async function renderStarted(handlers: { onExit?: () => void; onReplay?: (id: string) => void } = {}) {
  const { onExit = () => {}, onReplay = () => {} } = handlers;
  render(<ColorPlayScreen ctx={ctx} sessionId="sid-1" onExit={onExit} onReplay={onReplay} />);
  await act(async () => {});
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: /Start Game/ }));
  await act(async () => {});
}

describe('ColorPlay', () => {
  it('shows instructions first and does not play until Start Game', async () => {
    render(<ColorPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
    await act(async () => {});
    await act(async () => {});
    expect(
      screen.getByText('Watch the colors carefully, then repeat them in the exact same order.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/One wrong tap ends your run/)).toBeInTheDocument();
    // No playable buttons yet, and no timers running.
    expect(screen.queryByRole('button', { name: /Red/ })).not.toBeInTheDocument();
    await act(async () => {
      vi.runAllTimers();
    });
    expect(mockedApi.move).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Red/ })).not.toBeInTheDocument();
  });

  it('shows four labeled buttons and locks input during playback', async () => {
    await renderStarted();
    for (const name of ['Red', 'Green', 'Blue', 'Yellow']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeInTheDocument();
    }
    // Playback in progress: taps ignored.
    const red = screen.getByRole('button', { name: /Red/ });
    expect(red).toBeDisabled();
    fireEvent.click(red);
    expect(mockedApi.move).not.toHaveBeenCalled();

    // After playback, input unlocks.
    await act(async () => {
      vi.runAllTimers();
    });
    expect(screen.getByRole('button', { name: /Red/ })).not.toBeDisabled();
    expect(screen.getByText(/Your turn/)).toBeInTheDocument();
  });

  it('pauses two seconds with a countdown after a cleared round', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    // Finish level 2 (display [0, 2]) with the second correct tap.
    mockedApi.move.mockResolvedValue(
      startedState({
        level: 3,
        display: [0, 2, 1],
        position: 0,
        levels_completed: 1,
        moves: [
          { value: 0, hit: true },
          { value: 2, hit: true },
        ],
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Green/ }));
    await act(async () => {});
    expect(mockedApi.move).toHaveBeenCalledOnce();

    // Transition: message + countdown, input locked.
    expect(screen.getByText(/Correct! Get ready/)).toBeInTheDocument();
    expect(screen.getByText(/Get ready… 2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Red/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    await act(async () => {});
    expect(mockedApi.move).toHaveBeenCalledOnce();

    // Countdown ticks down, then the next level plays — still a single move.
    // (Step the chained 100ms ticks one act-flush at a time: each tick needs
    // a React flush before the next timeout is scheduled.)
    for (let i = 0; i < 10; i++) {
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
    }
    expect(screen.getByText(/Get ready… 1/)).toBeInTheDocument();
    for (let i = 0; i < 10; i++) {
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
    }
    expect(screen.queryByText(/Correct! Get ready/)).not.toBeInTheDocument();
    expect(screen.getByText(/Watch carefully/)).toBeInTheDocument();
    await act(async () => {
      vi.runAllTimers();
    });
    expect(screen.getByText(/Your turn/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Red/ })).not.toBeDisabled();
    expect(mockedApi.move).toHaveBeenCalledOnce();
  });

  it('flashes colors visibly during playback', async () => {
    await renderStarted();
    await act(async () => {
      // First flash fires at 450ms; the off-timer follows at 500ms
      // (test catalog uses playback_ms=50), so stop in between.
      vi.advanceTimersByTime(460);
    });
    // Active flash is bright and labelled.
    const flashing = screen.getByRole('button', { name: /flashing/ });
    expect(flashing.className).toMatch(/ring-4/);
    expect(flashing.className).toMatch(/scale-\[1\.06\]/);
  });

  it('cleans up timers on unmount without stale callbacks', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move.mockResolvedValue(
      startedState({
        level: 3,
        display: [0, 2, 1],
        position: 0,
        levels_completed: 1,
        moves: [{ value: 0, hit: true }],
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Green/ }));
    await act(async () => {});
    expect(screen.getByText(/Correct! Get ready/)).toBeInTheDocument();
    // Unmount the game mid-transition: pending timers must not throw.
    cleanup();
    await act(async () => {
      vi.runAllTimers();
    });
  });

  it('submits taps and advances on correct input', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move.mockResolvedValue(
      startedState({ position: 1, moves: [{ value: 0, hit: true }] }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    await act(async () => {});
    expect(mockedApi.move).toHaveBeenCalledOnce();
    const [, , color, moveId] = mockedApi.move.mock.calls[0];
    expect(color).toBe(0);
    expect(typeof moveId).toBe('string');
  });

  it('accepts a full correct sequence with no mid-level replay', async () => {
    // Regression: the prefix used to replay after EVERY tap while the
    // server kept advancing position, so repeating the displayed colors
    // from the start got a correct color rejected.
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move.mockResolvedValue(
      startedState({ position: 1, moves: [{ value: 0, hit: true }] }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    await act(async () => {});
    // Still input phase: no replay, position advanced.
    expect(screen.getByText(/tap 2 of 2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Red/ })).not.toBeDisabled();
    expect(screen.queryByText(/Watch carefully/)).not.toBeInTheDocument();

    // Second tap completes level 2 -> round transition, not rejection.
    mockedApi.move.mockResolvedValue(
      startedState({
        level: 3,
        display: [0, 2, 1],
        position: 0,
        levels_completed: 1,
        moves: [
          { value: 0, hit: true },
          { value: 2, hit: true },
        ],
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Green/ }));
    await act(async () => {});
    expect(screen.getByText(/Correct! Get ready/)).toBeInTheDocument();
    expect(mockedApi.move).toHaveBeenCalledTimes(2);
  });

  it('ends the run only on a truly wrong tap', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: { outcome: 'loss', score: 0, xp_earned: 0, secret: null },
      }),
    );
    // Display is [0, 2], so Yellow (3) is genuinely wrong.
    fireEvent.click(screen.getByRole('button', { name: /Yellow/ }));
    await act(async () => {});
    expect(screen.getByText('Run over!')).toBeInTheDocument();
    expect(mockedApi.move).toHaveBeenCalledOnce();
    const [, , color] = mockedApi.move.mock.calls[0];
    expect(color).toBe(3);
  });

  it('acknowledges each tap with a brief flash', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move.mockResolvedValue(
      startedState({ position: 1, moves: [{ value: 0, hit: true }] }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    await act(async () => {});
    expect(screen.getByRole('button', { name: /Red.*flashing/ })).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(screen.queryByRole('button', { name: /flashing/ })).not.toBeInTheDocument();
  });

  it('cleans up playback timers on unmount', async () => {
    await renderStarted(); // playback scheduled but not run
    cleanup();
    await act(async () => {
      vi.runAllTimers();
    });
  });

  it('processes rapid consecutive taps without waiting', async () => {
    // Level 3 start so both taps stay mid-level (no transition involved).
    mockedApi.colorState.mockResolvedValue(
      startedState({ display: [0, 2, 1], level: 3, max_level: 8 }),
    );
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move
      .mockResolvedValueOnce(
        startedState({
          display: [0, 2, 1],
          level: 3,
          max_level: 8,
          position: 1,
          moves: [{ value: 0, hit: true }],
        }),
      )
      .mockResolvedValueOnce(
        startedState({
          display: [0, 2, 1],
          level: 3,
          max_level: 8,
          position: 2,
          moves: [
            { value: 0, hit: true },
            { value: 2, hit: true },
          ],
        }),
      );
    // Two taps back-to-back: the second must be accepted immediately,
    // without waiting for the first request or the flash reset.
    // Display is [Red, Blue, Green]: tap Red (0), then Blue (2).
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    fireEvent.click(screen.getByRole('button', { name: /Blue/ }));
    await act(async () => {});
    expect(mockedApi.move).toHaveBeenCalledTimes(2);
    const calls = mockedApi.move.mock.calls;
    expect(calls[0][2]).toBe(0);
    expect(calls[1][2]).toBe(2);
    // Distinct idempotency ids per physical tap.
    expect(calls[0][3]).not.toBe(calls[1][3]);
    // Still mid-level input phase: no replay, no transition.
    expect(screen.getByText(/tap 3 of 3/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Red/ })).not.toBeDisabled();
    expect(screen.queryByText(/Watch carefully/)).not.toBeInTheDocument();
  });

  it('shows tap progress immediately, before the server responds', async () => {
    // Level 3 start; the move request stays pending while we assert.
    mockedApi.colorState.mockResolvedValue(
      startedState({ display: [0, 2, 1], level: 3, max_level: 8 }),
    );
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    expect(screen.getByText(/tap 1 of 3/)).toBeInTheDocument();
    let resolveMove!: (v: ColorState) => void;
    mockedApi.move.mockImplementation(
      () => new Promise<ColorState>((resolve) => { resolveMove = resolve; }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    fireEvent.click(screen.getByRole('button', { name: /Blue/ }));
    // No response yet — but progress already reflects both taps, and the
    // buttons were never disabled by the in-flight request.
    expect(screen.getByText(/tap 3 of 3/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Red/ })).not.toBeDisabled();
    await act(async () => {
      resolveMove(
        startedState({
          display: [0, 2, 1], level: 3, max_level: 8, position: 1,
          moves: [{ value: 0, hit: true }],
        }),
      );
    });
    await act(async () => {});
    // Server truth reconciles: one confirmed + one still pending.
    expect(screen.getByText(/tap 3 of 3/)).toBeInTheDocument();
  });

  it('accepts the same color repeatedly when the sequence requires it', async () => {
    mockedApi.colorState.mockResolvedValue(
      startedState({ display: [2, 2, 2], level: 3, max_level: 8 }),
    );
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.move
      .mockResolvedValueOnce(
        startedState({
          display: [2, 2, 2], level: 3, max_level: 8, position: 1,
          moves: [{ value: 2, hit: true }],
        }),
      )
      .mockResolvedValueOnce(
        startedState({
          display: [2, 2, 2], level: 3, max_level: 8, position: 2,
          moves: [
            { value: 2, hit: true },
            { value: 2, hit: true },
          ],
        }),
      )
      .mockResolvedValueOnce(
        startedState({
          display: [2, 2, 2, 0], level: 4, max_level: 8, position: 0,
          levels_completed: 1,
          moves: [
            { value: 2, hit: true },
            { value: 2, hit: true },
            { value: 2, hit: true },
          ],
        }),
      );
    const blue = screen.getByRole('button', { name: /Blue/ });
    fireEvent.click(blue);
    fireEvent.click(blue);
    fireEvent.click(blue);
    await act(async () => {});
    expect(mockedApi.move).toHaveBeenCalledTimes(3);
    expect(
      mockedApi.move.mock.calls.every(([, , color]) => color === 2),
    ).toBe(true);
    expect(screen.getByText(/Correct! Get ready/)).toBeInTheDocument();
  });

  it('drops taps queued behind a run-ending tap', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    // Display is [0, 2]: Red is correct, but the run ends on the first tap.
    mockedApi.move.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: { outcome: 'loss', score: 0, xp_earned: 0, secret: null },
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    fireEvent.click(screen.getByRole('button', { name: /Green/ }));
    await act(async () => {});
    // The second tap was buffered behind a terminal response: never sent.
    expect(mockedApi.move).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Run over!')).toBeInTheDocument();
  });

  it('abandons in-flight taps cleanly on unmount', async () => {
    await renderStarted();
    await act(async () => {
      vi.runAllTimers();
    });
    let resolveMove!: (v: ColorState) => void;
    mockedApi.move.mockImplementation(
      () => new Promise((resolve) => { resolveMove = resolve; }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Red/ }));
    cleanup();
    await act(async () => {
      resolveMove(startedState({ position: 1, moves: [{ value: 0, hit: true }] }));
    });
  });

  it('renders the finished panel with score, XP and best', async () => {
    mockedApi.colorState.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: { outcome: 'win', score: 8, xp_earned: 78, secret: null },
      }),
    );
    render(<ColorPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={() => {}} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('Sequence mastered!')).toBeInTheDocument();
    expect(screen.getByText(/Reached level 8/)).toBeInTheDocument();
    expect(screen.getByText(/New personal best!/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lobby' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Play again/ })).toBeInTheDocument();
  });

  it('cancels without recording and exits', async () => {
    const onExit = vi.fn();
    await renderStarted({ onExit });
    await act(async () => {
      vi.runAllTimers();
    });
    mockedApi.cancel.mockResolvedValue({ session_id: 'sid-1', status: 'abandoned' });
    const dialog = screen.getByRole('button', { name: 'Cancel game' });
    fireEvent.click(dialog);
    await act(async () => {});
    expect(mockedApi.cancel).toHaveBeenCalledWith('test', 'sid-1');
    expect(onExit).toHaveBeenCalledOnce();
  });

  it('replays at the same difficulty', async () => {
    const onReplay = vi.fn();
    mockedApi.colorState.mockResolvedValue(
      startedState({
        finished: true,
        status: 'completed',
        result: { outcome: 'loss', score: 2, xp_earned: 12, secret: null },
      }),
    );
    mockedApi.start = vi
      .fn()
      .mockResolvedValue({ session_id: 'sid-2' } as Awaited<ReturnType<typeof api.start>>);
    render(<ColorPlayScreen ctx={ctx} sessionId="sid-1" onExit={() => {}} onReplay={onReplay} />);
    await act(async () => {});
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Play again/ }));
    await act(async () => {});
    expect(mockedApi.start).toHaveBeenCalledWith('test', 'color_sequence', 'easy');
    expect(onReplay).toHaveBeenCalledWith('sid-2');
  });
});
