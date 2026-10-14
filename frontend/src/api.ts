/** Typed client for the BrainRush API. Secret game state never leaves the server. */

export interface ProfileData {
  level: number;
  total_xp: number;
  xp_into_level: number;
  xp_for_next: number;
  games_played: number;
  wins: number;
  losses: number;
  current_streak: number;
  longest_streak: number;
}

export interface DashboardData {
  user: { telegram_id: number; username: string | null; display_name: string | null };
  profile: ProfileData;
  today: { games_played: number; xp_earned: number };
  best_win_attempts: number | null;
  best_color_level: number | null;
  best_reflex_score?: number | null;
  rank: number;
  active_games: ActiveGame[];
}

export type ActiveGame = GameState | ColorState | ReflexState;

export interface DifficultyInfo {
  id: string;
  max_attempts: number;
  start_length?: number;
  playback_ms?: number;
}

export interface GameInfo {
  id: string;
  title: string;
  description: string;
  playable: boolean;
  difficulties: DifficultyInfo[];
  xp_rules?: Record<string, { win_first_try: number; win_last_try: number; loss: number }>;
}

export interface GuessEntry {
  value: number;
  hint: 'high' | 'low';
}

export interface GameResult {
  outcome: 'win' | 'loss';
  score: number;
  xp_earned: number;
  secret: number;
}

export interface GameState {
  session_id: string;
  game_type: string;
  difficulty: string;
  max_attempts: number;
  attempts_used: number;
  attempts_left: number;
  guesses: GuessEntry[];
  status: string;
  finished: boolean;
  result: GameResult | null;
}

export interface ColorMove {
  value: number;
  hit: boolean;
}

export interface ColorResult {
  outcome: 'win' | 'loss';
  score: number;
  xp_earned: number;
  secret: number | null;
}

export interface ColorState {
  session_id: string;
  game_type: string;
  difficulty: string;
  max_attempts: number;
  display: number[];
  position: number;
  level: number;
  max_level: number;
  levels_completed: number;
  moves: ColorMove[];
  status: string;
  finished: boolean;
  result: ColorResult | null;
}

export interface ReflexRoundInput {
  reaction_ms: number | null;
  false_start: boolean;
}

export interface ReflexRoundView {
  reaction_ms: number | null;
  false_start: boolean;
}

export interface ReflexResult {
  outcome: 'win' | 'loss';
  score: number;
  xp_earned: number;
  secret: number | null;
  avg_ms: number | null;
  best_ms: number | null;
  false_starts: number;
  rounds: ReflexRoundView[];
}

export interface ReflexState {
  session_id: string;
  game_type: string;
  difficulty: string;
  max_attempts: number;
  rounds_total?: number;
  rounds_played?: number;
  attempts_used?: number;
  attempts_left?: number;
  guesses: ReflexRoundView[];
  status: string;
  finished: boolean;
  result: ReflexResult | null;
}

export interface HistoryItem {
  session_id: string;
  game_type: string;
  status: string;
  score: number;
  started_at: string;
  ended_at: string | null;
  outcome: string | null;
  xp_earned: number;
}

export interface LeaderboardEntry {
  rank: number;
  display_name: string;
  username: string | null;
  level: number;
  total_xp: number;
  wins: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function baseUrl(): string {
  // Same-origin in local dev (vite proxies /api); configured host in prod.
  return (import.meta.env.VITE_API_URL as string | undefined) || '';
}

export function buildUrl(path: string): string {
  return `${baseUrl()}${path}`;
}

async function request<T>(path: string, initData: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') message = body.detail;
    } catch {
      /* keep default */
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const api = {
  me: (initData: string) => request<DashboardData>('/api/me', initData),
  games: (initData: string) => request<{ games: GameInfo[] }>('/api/games', initData),
  start: (initData: string, gameId: string, difficulty: string) =>
    request<GameState | ColorState | ReflexState>('/api/sessions', initData, {
      method: 'POST',
      body: JSON.stringify({ game_type: gameId, difficulty }),
    }),
  state: (initData: string, sessionId: string) =>
    request<GameState>(`/api/sessions/${sessionId}`, initData),
  colorState: (initData: string, sessionId: string) =>
    request<ColorState>(`/api/sessions/${sessionId}`, initData),
  guess: (initData: string, sessionId: string, value: number, clientGuessId: string) =>
    request<GameState>(`/api/sessions/${sessionId}/guess`, initData, {
      method: 'POST',
      body: JSON.stringify({ value, client_guess_id: clientGuessId }),
    }),
  move: (initData: string, sessionId: string, color: number, clientMoveId: string) =>
    request<ColorState>(`/api/sessions/${sessionId}/move`, initData, {
      method: 'POST',
      body: JSON.stringify({ color, client_move_id: clientMoveId }),
    }),
  finishReflex: (initData: string, sessionId: string, rounds: ReflexRoundInput[], clientSubmissionId: string) =>
    request<ReflexState>(`/api/sessions/${sessionId}/finish`, initData, {
      method: 'POST',
      body: JSON.stringify({ rounds, client_submission_id: clientSubmissionId }),
    }),
  reflexState: (initData: string, sessionId: string) =>
    request<ReflexState>(`/api/sessions/${sessionId}`, initData),
  cancel: (initData: string, sessionId: string) =>
    request<{ session_id: string; status: string }>(`/api/sessions/${sessionId}`, initData, {
      method: 'DELETE',
    }),
  history: (initData: string, limit = 20, offset = 0) =>
    request<{ items: HistoryItem[] }>(`/api/history?limit=${limit}&offset=${offset}`, initData),
  leaderboard: (initData: string, limit = 20, offset = 0) =>
    request<{ entries: LeaderboardEntry[]; my_rank: number | null }>(
      `/api/leaderboard?limit=${limit}&offset=${offset}`,
      initData,
    ),
};

export function newClientGuessId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}
