import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { ReferralPanel } from './components/ReferralPanel';
import { api } from './api';
import type { WebAppContext } from './telegram';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    api: {
      referralMine: vi.fn(),
      referralStats: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api, true);
const ctx = { initData: 'test', isDevMock: false } as WebAppContext;

beforeEach(() => {
  mockedApi.referralMine.mockResolvedValue({
    code: 'AB12CD34EF',
    link: 'https://t.me/somebot/play?startapp=AB12CD34EF',
    referrer_xp: 100,
    referred_xp: 25,
  });
  mockedApi.referralStats.mockResolvedValue({ referrals: 3, referral_xp: 300 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openPanel() {
  render(<ReferralPanel ctx={ctx} />);
  fireEvent.click(screen.getByRole('button', { name: /Refer a Friend/ }));
  await act(async () => {});
  await act(async () => {});
}

describe('ReferralPanel', () => {
  it('shows link, rewards, counts and XP after opening', async () => {
    await openPanel();
    expect(screen.getByText('https://t.me/somebot/play?startapp=AB12CD34EF')).toBeInTheDocument();
    expect(screen.getByText('+100 XP')).toBeInTheDocument();
    expect(screen.getByText('+25 XP')).toBeInTheDocument();
    expect(
      screen.getByText((_, el) => el?.textContent === '3 friends joined · +300 XP earned'),
    ).toBeInTheDocument();
    // Stable code: panel refetches on each open, backend returns same code.
    expect(mockedApi.referralMine).toHaveBeenCalledWith('test');
  });

  it('copies the link and confirms', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    await openPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Copy Link' }));
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith('https://t.me/somebot/play?startapp=AB12CD34EF');
    expect(screen.getByRole('button', { name: /Copied/ })).toBeInTheDocument();
  });

  it('shows an error with retry when loading fails', async () => {
    mockedApi.referralMine.mockRejectedValueOnce(new Error('boom'));
    render(<ReferralPanel ctx={ctx} />);
    fireEvent.click(screen.getByRole('button', { name: /Refer a Friend/ }));
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try again/i })).toBeInTheDocument();
  });

  it('falls back to code display when the link is unconfigured', async () => {
    mockedApi.referralMine.mockResolvedValue({
      code: 'ZZ99YY88XX',
      link: null,
      referrer_xp: 100,
      referred_xp: 25,
    });
    await openPanel();
    expect(screen.getByText(/Code: ZZ99YY88XX/)).toBeInTheDocument();
    expect(screen.getByText(/bot is configured/)).toBeInTheDocument();
  });
});
