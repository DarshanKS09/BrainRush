import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { FriendPanel } from './components/FriendPanel';
import { api, ApiError } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      friendMine: vi.fn(),
      friendsList: vi.fn(),
      friendAdd: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

const BOB = { display_name: 'Bob B', username: 'bob', level: 3, total_xp: 250 };

beforeEach(() => {
  mockedApi.friendMine.mockResolvedValue({ code: 'FR1ENDC0DE' });
  mockedApi.friendsList.mockResolvedValue({ friends: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openPanel() {
  render(<FriendPanel ctx={ctx} />);
  fireEvent.click(screen.getByRole('button', { name: /Add Friend/ }));
  await act(async () => {});
  await act(async () => {});
}

describe('FriendPanel', () => {
  it('shows my code with copy/share and an empty friends state', async () => {
    await openPanel();
    expect(screen.getByText('FR1ENDC0DE')).toBeInTheDocument();
    expect(
      screen.getByText('Share this code with a friend so they can add you on BrainRush.'),
    ).toBeInTheDocument();
    expect(screen.getByText('No friends yet — share your code above to get started.')).toBeInTheDocument();
    expect(mockedApi.friendMine).toHaveBeenCalledWith('test');
  });

  it('copies the code and confirms', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    await openPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith('FR1ENDC0DE');
    expect(screen.getByRole('button', { name: /Copied/ })).toBeInTheDocument();
  });

  it('adds a friend successfully and refreshes the list without reload', async () => {
    mockedApi.friendAdd.mockResolvedValue({ added: true, already: false, friend: BOB });
    mockedApi.friendsList
      .mockResolvedValueOnce({ friends: [] })
      .mockResolvedValueOnce({ friends: [BOB] });
    await openPanel();
    fireEvent.change(screen.getByLabelText('Friend code'), { target: { value: 'BOBCODE99' } });
    fireEvent.click(screen.getByRole('button', { name: /^Add Friend$/ }));
    await act(async () => {});
    await act(async () => {});
    expect(mockedApi.friendAdd).toHaveBeenCalledWith('test', 'BOBCODE99');
    expect(screen.getByText('Friend added successfully!')).toBeInTheDocument();
    expect(screen.getByText('Bob B')).toBeInTheDocument();
    expect(mockedApi.friendsList).toHaveBeenCalledTimes(2);
  });

  it('reports already-friends without duplicating', async () => {
    mockedApi.friendsList.mockResolvedValue({ friends: [BOB] });
    mockedApi.friendAdd.mockResolvedValue({ added: false, already: true, friend: BOB });
    await openPanel();
    fireEvent.change(screen.getByLabelText('Friend code'), { target: { value: 'BOBCODE99' } });
    fireEvent.click(screen.getByRole('button', { name: /^Add Friend$/ }));
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('You are already friends.')).toBeInTheDocument();
    expect(screen.getAllByText('Bob B')).toHaveLength(1);
  });

  it('rejects empty input client-side', async () => {
    await openPanel();
    fireEvent.click(screen.getByRole('button', { name: /^Add Friend$/ }));
    await act(async () => {});
    expect(screen.getByText('Please enter a friend code.')).toBeInTheDocument();
    expect(mockedApi.friendAdd).not.toHaveBeenCalled();
  });

  it('maps self-add, unknown code, and network failures to clear messages', async () => {
    await openPanel();
    const input = screen.getByLabelText('Friend code');
    const button = screen.getByRole('button', { name: /^Add Friend$/ });

    mockedApi.friendAdd.mockRejectedValueOnce(new ApiError(409, 'You cannot add yourself as a friend.'));
    fireEvent.change(input, { target: { value: 'FR1ENDC0DE' } });
    fireEvent.click(button);
    await act(async () => {});
    expect(screen.getByText('You cannot add yourself as a friend.')).toBeInTheDocument();

    mockedApi.friendAdd.mockRejectedValueOnce(new ApiError(404, 'Friend code not found. Please check the code.'));
    fireEvent.change(input, { target: { value: 'NOPE123456' } });
    fireEvent.click(button);
    await act(async () => {});
    expect(screen.getByText('Friend code not found. Please check the code.')).toBeInTheDocument();

    mockedApi.friendAdd.mockRejectedValueOnce(new Error('offline'));
    fireEvent.change(input, { target: { value: 'RETRY12345' } });
    fireEvent.click(button);
    await act(async () => {});
    expect(screen.getByText('offline')).toBeInTheDocument();
    // Recoverable: retrying works.
    mockedApi.friendAdd.mockResolvedValueOnce({ added: true, already: false, friend: BOB });
    mockedApi.friendsList.mockResolvedValueOnce({ friends: [BOB] });
    fireEvent.click(button);
    await act(async () => {});
    await act(async () => {});
    expect(screen.getByText('Friend added successfully!')).toBeInTheDocument();
  });

  it('shows loading and error-with-retry states', async () => {
    mockedApi.friendMine.mockRejectedValueOnce(new Error('boom'));
    render(<FriendPanel ctx={ctx} />);
    fireEvent.click(screen.getByRole('button', { name: /Add Friend/ }));
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try again/i })).toBeInTheDocument();
  });
});
