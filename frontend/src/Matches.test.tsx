import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MatchesScreen, CreateMatchForm } from './screens/Matches';
import { MatchDetailScreen } from './screens/MatchDetail';
import { MatchSubmitBanner } from './components/MatchSubmit';
import { api } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      matchInvites: vi.fn(),
      matchMine: vi.fn(),
      matchCreate: vi.fn(),
      matchGet: vi.fn(),
      matchJoin: vi.fn(),
      matchLink: vi.fn(),
      matchStart: vi.fn(),
      matchSubmit: vi.fn(),
      matchFinalize: vi.fn(),
      matchRematch: vi.fn(),
      matchCancel: vi.fn(),
      matchLeave: vi.fn(),
      friendsList: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;
const noop = () => {};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

const lobbyView = {
  match_id: 'm1',
  game_type: 'number_guessing',
  mode: 'duel',
  difficulty: 'hard',
  status: 'lobby',
  host_user_id: 'u1',
  count: 1,
  min_players: 2,
  max_players: 2,
  token_expires_at: null,
  created_at: null,
  started_at: null,
  deadline: null,
  finished_at: null,
  participants: [
    {
      user_id: 'u1', display_name: 'Host', username: null, level: 1,
      is_host: true, is_me: true, finished: false, score: null,
      rank: null, xp_earned: 0, online: true, joined_at: null,
    },
  ],
};

describe('MatchesScreen', () => {
  it('lists invites with join and shows my matches', async () => {
    mockedApi.matchInvites.mockResolvedValue({
      items: [
        {
          match_id: 'm9', game_type: 'color_sequence', mode: 'ffa',
          difficulty: 'hard', host_display_name: 'Amy', participants: 2,
          max_players: 8, invited_at: null,
        },
      ],
    });
    mockedApi.matchMine.mockResolvedValue({
      items: [
        {
          match_id: 'm1', game_type: 'number_guessing', mode: 'duel',
          difficulty: 'hard', status: 'lobby', my_rank: null,
          participants: 1, max_players: 2, finished_at: null, created_at: null,
        },
      ],
    });
    const onOpen = vi.fn();
    render(<MatchesScreen ctx={ctx} onOpen={onOpen} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/Amy/)).toBeInTheDocument();
    expect(screen.queryByText(/No pending invitations/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Join' }));
    await act(async () => {});
    expect(mockedApi.matchJoin).toHaveBeenCalled();
  });

  it('shows an empty state when there is nothing', async () => {
    mockedApi.matchInvites.mockResolvedValue({ items: [] });
    mockedApi.matchMine.mockResolvedValue({ items: [] });
    render(<MatchesScreen ctx={ctx} onOpen={noop} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/No pending invitations/)).toBeInTheDocument();
    expect(screen.getByText(/No matches yet/)).toBeInTheDocument();
  });
});

describe('CreateMatchForm', () => {
  it('creates a duel lobby with defaults', async () => {
    mockedApi.matchCreate.mockResolvedValue(lobbyView as never);
    const onCreated = vi.fn();
    render(<CreateMatchForm ctx={ctx} gameId="number_guessing" onCreated={onCreated} />);
    fireEvent.click(screen.getByRole('button', { name: /Create match lobby/ }));
    await act(async () => {});
    expect(mockedApi.matchCreate).toHaveBeenCalledWith(
      'test', 'number_guessing', 'duel', 'hard',
    );
    expect(onCreated).toHaveBeenCalledWith('m1');
  });
});

describe('MatchDetailScreen', () => {
  it('renders the lobby with start control for the host', async () => {
    mockedApi.matchGet.mockResolvedValue(lobbyView as never);
    render(<MatchDetailScreen ctx={ctx} matchId="m1" onExit={noop} onPlay={noop} />);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText(/Number Guessing/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start match/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Invite link/ })).toBeInTheDocument();
  });

  it('shows final results with ranks and rematch', async () => {
    mockedApi.matchGet.mockResolvedValue({
      match_id: 'm1',
      game_type: 'reflex_rush',
      mode: 'duel',
      difficulty: 'hard',
      status: 'completed',
      finished_at: null,
      count: 2,
      participants: [
        {
          user_id: 'u1', display_name: 'Host', username: null, level: 2,
          is_host: true, is_me: true, finished: true, score: 30,
          rank: 1, xp_earned: 20, online: true, joined_at: null,
        },
        {
          user_id: 'u2', display_name: 'Guest', username: null, level: 1,
          is_host: false, is_me: false, finished: true, score: 10,
          rank: 2, xp_earned: 10, online: false, joined_at: null,
        },
      ],
    } as never);
    render(<MatchDetailScreen ctx={ctx} matchId="m1" onExit={noop} onPlay={noop} />);
    await act(async () => {});
    await act(async () => {});
    // Timers keep polling; unmount to clear.
    expect(screen.getByText(/#1 Host \(you\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Rematch/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Share results/ })).toBeInTheDocument();
  });
});

describe('MatchSubmitBanner', () => {
  it('submits once and shows confirmation', async () => {
    mockedApi.matchSubmit.mockResolvedValue(lobbyView as never);
    const onBack = vi.fn();
    render(<MatchSubmitBanner ctx={ctx} matchId="m1" sessionId="s1" onBackToMatch={onBack} />);
    expect(screen.getByText(/Submitting to match/)).toBeInTheDocument();
    await act(async () => {});
    expect(mockedApi.matchSubmit).toHaveBeenCalledTimes(1);
    expect(mockedApi.matchSubmit).toHaveBeenCalledWith('test', 'm1', 's1');
    expect(screen.getByText(/submitted to the match/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Back to match/ }));
    expect(onBack).toHaveBeenCalled();
  });
});
