import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { GamesScreen } from './screens/Games';
import { api } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: { games: vi.fn(), start: vi.fn() },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;
const noop = () => {};

beforeEach(() => {
  mockedApi.games.mockResolvedValue({
    games: [
      {
        id: 'reflex_rush',
        title: 'Reflex Rush',
        description: 'Tap fast.',
        playable: true,
        difficulties: [
          { id: 'easy', max_attempts: 5, wait_min_ms: 2000, wait_max_ms: 2000 },
          { id: 'medium', max_attempts: 5, wait_min_ms: 1000, wait_max_ms: 3000 },
          { id: 'hard', max_attempts: 5, wait_min_ms: 500, wait_max_ms: 3500 },
        ],
        xp_rules: {
          easy: { win_bonus: 15, win_avg_ms: 650 },
          medium: { win_bonus: 25, win_avg_ms: 550 },
          hard: { win_bonus: 40, win_avg_ms: 500 },
        },
      },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openReflexModal() {
  render(<GamesScreen ctx={ctx} onStart={noop} />);
  await act(async () => {});
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  await act(async () => {});
}

describe('GamesScreen reflex difficulty', () => {
  it('shows the exact wait behavior for the selected mode', async () => {
    await openReflexModal();
    // Medium is the default selection.
    expect(screen.getByText(/Wait varies: 1–3 s/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Easy/ }));
    await act(async () => {});
    expect(screen.getByText(/Same wait every round: 2 s/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Hard/ }));
    await act(async () => {});
    expect(screen.getByText(/Wait varies: 0\.5–3\.5 s/)).toBeInTheDocument();
  });

  it('documents false starts, scoring and the win rule', async () => {
    await openReflexModal();
    expect(screen.getByText(/false start.*0 points/i)).toBeInTheDocument();
    expect(screen.getByText(/Win: average ≤ 550 ms with at most 1 false start/)).toBeInTheDocument();
  });
});
