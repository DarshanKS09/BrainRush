import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MatchSetupScreen, JoinByCode } from './screens/MatchSetup';
import { GamesScreen } from './screens/Games';
import { api } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: { games: vi.fn(), start: vi.fn(), matchCreate: vi.fn(), matchJoinByCode: vi.fn() },
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
        playable: true, difficulties: [{ id: 'hard', max_attempts: 7 }],
        multiplayer: { modes: ['duel', 'ffa', 'tournament'] },
      },
      {
        id: 'memory_match', title: 'Memory Match', description: 'Soon.',
        playable: false, difficulties: [], multiplayer: null,
      },
      {
        id: 'color_sequence', title: 'Color Sequence', description: 'Repeat.',
        playable: true, difficulties: [{ id: 'hard', max_attempts: 12 }],
        multiplayer: null,
      },
    ],
  };
}

beforeEach(() => {
  mockedApi.games.mockResolvedValue(catalog());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openSetup(props: Record<string, unknown> = {}) {
  render(
    <MatchSetupScreen ctx={ctx} onOpenMatch={noop} onBack={noop} {...props} />,
  );
  await act(async () => {});
  await act(async () => {});
}

describe('MatchSetupScreen (Play With Friends flow)', () => {
  it('lists registry games, enables multiplayer ones, marks solo-only', async () => {
    await openSetup();
    expect(screen.getByText('Number Guessing')).toBeInTheDocument();
    expect(screen.getByText(/Multiplayer: duel, ffa, tournament/)).toBeInTheDocument();
    expect(screen.getByText('Solo only for now')).toBeInTheDocument();
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
    // Solo-only game button is disabled; multiplayer default is selected.
    expect(screen.getByRole('button', { name: /Color Sequence/ })).toBeDisabled();
  });

  it('creates a duel room with defaults and opens its lobby', async () => {
    mockedApi.matchCreate.mockResolvedValue({ match_id: 'm1', room_code: 'ABC123' } as never);
    const onOpenMatch = vi.fn();
    await openSetup({ onOpenMatch });
    fireEvent.click(screen.getByRole('button', { name: /Create private room/ }));
    await act(async () => {});
    expect(mockedApi.matchCreate).toHaveBeenCalledWith(
      'test', 'number_guessing', 'duel', 'medium', undefined,
    );
    expect(onOpenMatch).toHaveBeenCalledWith('m1');
  });

  it('configures ffa max players within the mode range', async () => {
    mockedApi.matchCreate.mockResolvedValue({ match_id: 'm2', room_code: 'ZZ9X11' } as never);
    await openSetup();
    fireEvent.click(screen.getByRole('button', { name: /Free-for-All/ }));
    fireEvent.click(screen.getByRole('button', { name: 'More max players' }));
    fireEvent.click(screen.getByRole('button', { name: /Create private room/ }));
    await act(async () => {});
    expect(mockedApi.matchCreate).toHaveBeenCalledWith(
      'test', 'number_guessing', 'ffa', 'medium', 5,
    );
  });

  it('shows creation errors without leaving the flow', async () => {
    mockedApi.matchCreate.mockRejectedValueOnce(new Error('offline'));
    await openSetup();
    fireEvent.click(screen.getByRole('button', { name: /Create private room/ }));
    await act(async () => {});
    expect(screen.getByText('offline')).toBeInTheDocument();
  });
});

describe('JoinByCode', () => {
  it('prompts on empty input and joins on a valid code', async () => {
    mockedApi.matchJoinByCode.mockResolvedValue({ match_id: 'm9' } as never);
    const onJoined = vi.fn();
    render(<JoinByCode ctx={ctx} onJoined={onJoined} />);
    fireEvent.click(screen.getByRole('button', { name: 'Join room by code' }));
    expect(screen.getByText(/Enter the room code/)).toBeInTheDocument();
    expect(mockedApi.matchJoinByCode).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Room code'), { target: { value: 'kq7x2p' } });
    fireEvent.click(screen.getByRole('button', { name: 'Join room by code' }));
    await act(async () => {});
    expect(mockedApi.matchJoinByCode).toHaveBeenCalledWith('test', 'KQ7X2P');
    expect(onJoined).toHaveBeenCalledWith('m9');
  });

  it('maps unknown codes to a clear message', async () => {
    const { ApiError } = await import('./api');
    mockedApi.matchJoinByCode.mockRejectedValueOnce(new ApiError(404, 'Room not found.'));
    render(<JoinByCode ctx={ctx} onJoined={noop} />);
    fireEvent.change(screen.getByLabelText('Room code'), { target: { value: 'NOPE99' } });
    fireEvent.click(screen.getByRole('button', { name: 'Join room by code' }));
    await act(async () => {});
    expect(screen.getByText(/Room not found/)).toBeInTheDocument();
  });
});

describe('GamesScreen Play With Friends entry', () => {
  it('opens the dedicated setup flow without touching matches lists', async () => {
    mockedApi.games.mockResolvedValue({ games: [] });
    const onSetupMatch = vi.fn();
    render(<GamesScreen ctx={ctx} onStart={noop} onSetupMatch={onSetupMatch} />);
    await act(async () => {});
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Play With Friends/ }));
    expect(onSetupMatch).toHaveBeenCalledOnce();
    expect(mockedApi.games).toHaveBeenCalledTimes(1);
  });
});
