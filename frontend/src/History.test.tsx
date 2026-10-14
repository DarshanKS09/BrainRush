import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act, within } from '@testing-library/react';
import { ProfileScreen } from './screens/Profile';
import { HistoryScreen } from './screens/History';
import { api } from './api';
import type { DashboardData, HistoryItem } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: { me: vi.fn(), history: vi.fn() },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

function dashboard(): DashboardData {
  return {
    user: { telegram_id: 1, username: 't', display_name: 'T' },
    profile: {
      level: 2, total_xp: 150, xp_into_level: 50, xp_for_next: 100,
      games_played: 9, wins: 5, losses: 4, current_streak: 1, longest_streak: 3,
    },
    today: { games_played: 1, xp_earned: 10 },
    best_win_attempts: 3,
    best_color_level: null,
    best_reflex_score: null,
    rank: 7,
    active_games: [],
  };
}

function item(i: number, overrides: Partial<HistoryItem> = {}): HistoryItem {
  return {
    session_id: `sid-${i}`,
    game_type: 'number_guessing',
    status: 'completed',
    score: i,
    started_at: `2026-10-${String(i).padStart(2, '0')}T00:00:00+00:00`,
    ended_at: `2026-10-${String(i).padStart(2, '0')}T00:05:00+00:00`,
    outcome: i % 2 === 0 ? 'win' : 'loss',
    xp_earned: 10,
    ...overrides,
  };
}

beforeEach(() => {
  mockedApi.me.mockResolvedValue(dashboard());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Profile compact history', () => {
  it('fetches only five entries for the preview', async () => {
    mockedApi.history.mockResolvedValue({ items: [item(1)] });
    render(<ProfileScreen ctx={ctx} onViewHistory={() => {}} />);
    await act(async () => {});
    expect(mockedApi.history).toHaveBeenCalledWith('test', 5, 0);
  });

  it('shows at most five entries newest-first with a View Full History button', async () => {
    // Backend returns newest first; the preview renders the first five.
    const eight = [8, 7, 6, 5, 4, 3, 2, 1].map((i) => item(i));
    mockedApi.history.mockResolvedValue({ items: eight });
    const onViewHistory = vi.fn();
    render(<ProfileScreen ctx={ctx} onViewHistory={onViewHistory} />);
    await act(async () => {});
    const list = screen.getByRole('list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    expect(screen.queryByText(/sid-/)).not.toBeInTheDocument(); // ids not rendered
    fireEvent.click(screen.getByRole('button', { name: /View Full History/ }));
    expect(onViewHistory).toHaveBeenCalledOnce();
  });

  it('shows empty state without the history button', async () => {
    mockedApi.history.mockResolvedValue({ items: [] });
    render(<ProfileScreen ctx={ctx} onViewHistory={() => {}} />);
    await act(async () => {});
    expect(screen.getByText('No games played yet.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View Full History/ })).not.toBeInTheDocument();
  });

  it('shows error state with retry and keeps profile stats intact', async () => {
    mockedApi.history.mockRejectedValueOnce(new Error('boom'));
    render(<ProfileScreen ctx={ctx} onViewHistory={() => {}} />);
    await act(async () => {});
    expect(screen.getByText('boom')).toBeInTheDocument();
    mockedApi.history.mockResolvedValue({ items: [item(1)] });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    await act(async () => {});
    // Stats survive the history failure/retry cycle.
    expect(screen.getByText('Total XP')).toBeInTheDocument();
  });
});

describe('HistoryScreen full list', () => {
  it('pages through all history with existing limit/offset', async () => {
    const page1 = Array.from({ length: 20 }, (_, k) => item(k + 1));
    const page2 = [item(21), item(22)];
    mockedApi.history
      .mockResolvedValueOnce({ items: page1 })
      .mockResolvedValueOnce({ items: page2 });
    const onBack = vi.fn();
    render(<HistoryScreen ctx={ctx} onBack={onBack} />);
    await act(async () => {});
    expect(mockedApi.history).toHaveBeenCalledWith('test', 20, 0);
    expect(screen.getAllByRole('listitem')).toHaveLength(20);
    fireEvent.click(screen.getByRole('button', { name: /Load more/ }));
    await act(async () => {});
    expect(mockedApi.history).toHaveBeenCalledWith('test', 20, 20);
    // Beyond the first five (and the first page) remains accessible.
    expect(screen.getAllByRole('listitem')).toHaveLength(22);
    expect(screen.queryByRole('button', { name: /Load more/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Back to profile/ }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('shows game names, scores, XP and dates per row', async () => {
    mockedApi.history.mockResolvedValue({
      items: [item(1, { game_type: 'color_sequence', score: 6, xp_earned: 42 })],
    });
    render(<HistoryScreen ctx={ctx} onBack={() => {}} />);
    await act(async () => {});
    const row = screen.getByRole('listitem');
    expect(within(row).getByText(/Color Sequence/)).toBeInTheDocument();
    expect(within(row).getByText(/Lv 6/)).toBeInTheDocument();
    expect(within(row).getByText(/\+42 XP/)).toBeInTheDocument();
  });

  it('shows empty and error states', async () => {
    mockedApi.history.mockResolvedValueOnce({ items: [] });
    const { unmount } = render(<HistoryScreen ctx={ctx} onBack={() => {}} />);
    await act(async () => {});
    expect(screen.getByText('No games played yet.')).toBeInTheDocument();
    unmount();
    cleanup();
    mockedApi.history.mockRejectedValueOnce(new Error('down'));
    render(<HistoryScreen ctx={ctx} onBack={() => {}} />);
    await act(async () => {});
    expect(screen.getByText('down')).toBeInTheDocument();
  });
});
