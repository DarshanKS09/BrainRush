import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MatchSetupScreen } from './screens/MatchSetup';
import { api } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      games: vi.fn(),
      matchCreate: vi.fn(),
      matchJoin: vi.fn(),
      matchJoinByCode: vi.fn(),
      matchInvites: vi.fn(),
      matchMine: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;
const noop = () => {};

function catalog() {
  return {
    games: [
      {
        id: 'number_guessing', title: 'Number Guessing', description: 'Guess it.',
        playable: true, difficulties: [{ id: 'medium', max_attempts: 10 }],
        multiplayer: { modes: ['duel', 'ffa', 'tournament'] },
      },
      {
        id: 'perfect_second', title: 'Perfect Second', description: 'Stop on time.',
        playable: true, difficulties: [{ id: 'medium', max_attempts: 1 }],
        multiplayer: { modes: ['duel'] },
      },
    ],
  };
}

beforeEach(() => {
  mockedApi.games.mockResolvedValue(catalog());
  mockedApi.matchInvites.mockResolvedValue({ items: [] });
  mockedApi.matchMine.mockResolvedValue({ items: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openHub() {
  render(<MatchSetupScreen ctx={ctx} onOpenMatch={noop} onBack={noop} />);
  await act(async () => {});
  await act(async () => {});
}

describe('Play With Friends hub', () => {
  it('shows Create Room and Join Room actions immediately, side by side', async () => {
    await openHub();
    const create = screen.getByRole('button', { name: /Create Room/ });
    const join = screen.getByRole('button', { name: /Join Room/ });
    expect(create).toBeInTheDocument();
    expect(join).toBeInTheDocument();
    // Both actions share one row group at the top of the hub.
    expect(create.parentElement).toBe(join.parentElement);
    expect(create.parentElement?.className).toMatch(/grid-cols-2/);
  });

  it('opens the create panel by default and toggles to the join panel', async () => {
    await openHub();
    // Create form visible without any toggle.
    expect(screen.getByRole('button', { name: /Create private room/ })).toBeInTheDocument();
    expect(screen.queryByLabelText('Room code')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Join Room/ }));
    await act(async () => {});
    expect(screen.getByLabelText('Room code')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Create private room/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Create Room/ }));
    await act(async () => {});
    expect(screen.getByRole('button', { name: /Create private room/ })).toBeInTheDocument();
  });

  it('lists invitations and history below the actions', async () => {
    mockedApi.matchInvites.mockResolvedValue({
      items: [
        {
          match_id: 'm9', game_type: 'perfect_second', mode: 'duel',
          difficulty: 'hard', host_display_name: 'Amy', participants: 1,
          max_players: 2, invited_at: null,
        },
      ],
    });
    await openHub();
    expect(screen.getByText(/Match invitations/)).toBeInTheDocument();
    expect(screen.getByText(/Amy/)).toBeInTheDocument();
    expect(screen.getByText(/My matches/)).toBeInTheDocument();
  });

  it('lists only the selected game adapter modes', async () => {
    await openHub();
    // Default game (number_guessing) supports every mode.
    expect(screen.getByRole('button', { name: /Free-for-All/ })).toBeInTheDocument();
    // Switch to Perfect Second, which supports duel only.
    fireEvent.click(screen.getByRole('button', { name: /Perfect Second/ }));
    await act(async () => {});
    expect(screen.getByRole('button', { name: '1v1 Duel 2 players' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Free-for-All/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Tournament/ })).toBeNull();
  });

  it('creates through the backend only on confirm and opens the lobby', async () => {
    mockedApi.matchCreate.mockResolvedValue({ match_id: 'm1', room_code: 'ABC123' } as never);
    const onOpenMatch = vi.fn();
    render(<MatchSetupScreen ctx={ctx} onOpenMatch={onOpenMatch} onBack={noop} />);
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.matchCreate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Perfect Second/ }));
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Create private room/ }));
    await act(async () => {});
    // Duel-only game: no max_players sent, game + mode confirmed by the user.
    expect(mockedApi.matchCreate).toHaveBeenCalledWith(
      'test', 'perfect_second', 'duel', 'medium', undefined,
    );
    expect(onOpenMatch).toHaveBeenCalledWith('m1');
  });
});
