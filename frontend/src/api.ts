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
  best_perfect_error_ms?: number | null;
  rank: number;
  active_games: ActiveGame[];
}

export type ActiveGame = GameState | ColorState | ReflexState | PerfectState | MazeState;

export interface DifficultyInfo {
  id: string;
  max_attempts: number;
  start_length?: number;
  playback_ms?: number;
  wait_min_ms?: number;
  wait_max_ms?: number;
  target_min_ms?: number;
  target_max_ms?: number;
  target_step_ms?: number;
  rows?: number;
  cols?: number;
  branching?: number;
  par_time_s?: number;
}

export interface GameXpRules {
  win_first_try?: number;
  win_last_try?: number;
  loss?: number;
  win?: number;
  loss_per_level?: number;
  win_bonus?: number;
  xp_perfect?: number;
  xp_good?: number;
  xp_slow?: number;
  win_avg_ms?: number;
  wait_min_ms?: number;
  wait_max_ms?: number;
}

export interface GameInfo {
  id: string;
  title: string;
  description: string;
  playable: boolean;
  difficulties: DifficultyInfo[];
  xp_rules?: Record<string, GameXpRules>;
  multiplayer?: { modes: string[] } | null;
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

export interface PerfectResult {
  outcome: 'win' | 'loss';
  score: number;
  xp_earned: number;
  secret: number | null;
  target_ms: number;
  actual_ms: number;
  error_ms: number;
  accuracy_percent: number;
}

export interface PerfectState {
  session_id: string;
  game_type: string;
  difficulty: string;
  target_ms: number;
  max_attempts: number;
  attempts_used: number;
  attempts_left: number;
  status: string;
  finished: boolean;
  result: PerfectResult | null;
}

export interface MazeCell {
  r: number;
  c: number;
  walls: { up: boolean; right: boolean; down: boolean; left: boolean };
}

export interface MazeResult {
  outcome: 'win';
  score: number;
  xp_earned: number;
  elapsed_ms: number;
  moves: number;
  xp_breakdown: { base: number; time_bonus: number; path_bonus: number; total: number };
}

export interface MazeState {
  session_id: string;
  game_type: string;
  difficulty: string;
  max_attempts: number;
  attempts_used: number;
  attempts_left: number;
  maze: { rows: number; cols: number; start: number[]; exit: number[]; cells: MazeCell[] };
  player: { r: number; c: number };
  exit: { r: number; c: number };
  valid_directions: string[];
  moves: number;
  elapsed_ms: number | null;
  finished: boolean;
  result: MazeResult | null;
}

export interface ReferralLink {
  code: string;
  link: string | null;
  referrer_xp: number;
  referred_xp: number;
}

export interface ReferralClaim {
  credited: boolean;
  already: boolean;
  code: string;
  referrer_xp: number;
  referred_xp: number;
}

export interface ReferralStats {
  referrals: number;
  referral_xp: number;
}

export interface FriendCode {
  code: string;
}

export interface FriendEntry {
  display_name: string | null;
  username: string | null;
  level: number;
  total_xp: number;
}

export interface FriendAddResult {
  added: boolean;
  already: boolean;
  friend: FriendEntry;
}

export interface MatchParticipant {
  user_id: string;
  display_name: string;
  username: string | null;
  level: number;
  is_host: boolean;
  is_me: boolean;
  finished: boolean;
  score: number | null;
  rank: number | null;
  xp_earned: number;
  online: boolean;
  joined_at: string | null;
}

export interface MatchView {
  match_id: string;
  game_type: string;
  mode: string;
  difficulty: string;
  status: string;
  host_user_id: string;
  count: number;
  min_players: number;
  max_players: number;
  room_code: string;
  target_ms?: number | null;
  token_expires_at: string | null;
  created_at: string | null;
  started_at: string | null;
  deadline: string | null;
  finished_at: string | null;
  participants: MatchParticipant[];
}

export interface MatchResultView {
  match_id: string;
  game_type: string;
  mode: string;
  difficulty: string;
  status: string;
  finished_at: string | null;
  participants: MatchParticipant[];
  count: number;
}

export interface MatchListItem {
  match_id: string;
  game_type: string;
  mode: string;
  difficulty: string;
  status: string;
  my_rank: number | null;
  participants: number;
  max_players: number;
  finished_at: string | null;
  created_at: string | null;
}

export interface MatchInviteItem {
  match_id: string;
  game_type: string;
  mode: string;
  difficulty: string;
  host_display_name: string;
  participants: number;
  max_players: number;
  invited_at: string | null;
}

export interface MatchInviteLink {
  token: string;
  link: string | null;
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

async function request<T>(
  path: string,
  initData: string,
  init?: RequestInit,
  timeoutMs?: number,
): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...init,
    signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : init?.signal ?? null,
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

export const SUBMIT_TIMEOUT_MS = 25000;

export const api = {
  me: (initData: string) => request<DashboardData>('/api/me', initData),
  games: (initData: string) => request<{ games: GameInfo[] }>('/api/games', initData),
  start: (initData: string, gameId: string, difficulty: string, matchId?: string | null) =>
    request<GameState | ColorState | ReflexState | PerfectState>('/api/sessions', initData, {
      method: 'POST',
      // match_id is omitted for plain solo starts (unchanged request shape);
      // match-linked starts carry it so the server can resolve shared targets.
      body: JSON.stringify(matchId
        ? { game_type: gameId, difficulty, match_id: matchId }
        : { game_type: gameId, difficulty }),
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
    }, SUBMIT_TIMEOUT_MS),
  reflexState: (initData: string, sessionId: string) =>
    request<ReflexState>(`/api/sessions/${sessionId}`, initData),
  perfectState: (initData: string, sessionId: string) =>
    request<PerfectState>(`/api/sessions/${sessionId}`, initData),
  stopPerfect: (initData: string, sessionId: string, actualMs: number, clientSubmissionId: string) =>
    request<PerfectState>(`/api/sessions/${sessionId}/stop`, initData, {
      method: 'POST',
      body: JSON.stringify({ actual_ms: actualMs, client_submission_id: clientSubmissionId }),
    }, SUBMIT_TIMEOUT_MS),
  mazeState: (initData: string, sessionId: string) =>
    request<MazeState>(`/api/sessions/${sessionId}`, initData),
  mazeMove: (initData: string, sessionId: string, direction: string, clientMoveId: string) =>
    request<MazeState>(`/api/sessions/${sessionId}/direction`, initData, {
      method: 'POST',
      body: JSON.stringify({ direction, client_move_id: clientMoveId }),
    }, SUBMIT_TIMEOUT_MS),
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
  referralMine: (initData: string) =>
    request<ReferralLink>('/api/referrals/mine', initData),
  referralClaim: (initData: string, code: string) =>
    request<ReferralClaim>('/api/referrals/claim', initData, {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  referralStats: (initData: string) =>
    request<ReferralStats>('/api/referrals/stats', initData),
  friendMine: (initData: string) =>
    request<FriendCode>('/api/friends/mine', initData),
  friendsList: (initData: string) =>
    request<{ friends: FriendEntry[] }>('/api/friends', initData),
  friendAdd: (initData: string, code: string) =>
    request<FriendAddResult>('/api/friends/add', initData, {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  matchCreate: (initData: string, game_type: string, mode: string, difficulty: string, max_players?: number) =>
    request<MatchView>('/api/matches', initData, {
      method: 'POST',
      body: JSON.stringify({ game_type, mode, difficulty, max_players: max_players ?? null }),
    }),
  matchMine: (initData: string, limit = 20, offset = 0) =>
    request<{ items: MatchListItem[] }>(`/api/matches/mine?limit=${limit}&offset=${offset}`, initData),
  matchInvites: (initData: string) =>
    request<{ items: MatchInviteItem[] }>('/api/matches/invites', initData),
  matchGet: (initData: string, matchId: string) =>
    request<MatchView | MatchResultView>(`/api/matches/${matchId}`, initData),
  matchJoinByToken: (initData: string, token: string) =>
    request<MatchView>('/api/matches/join', initData, {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  matchJoinByCode: (initData: string, code: string) =>
    request<MatchView>('/api/matches/join-by-code', initData, {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  matchJoin: (initData: string, matchId: string) =>
    request<MatchView>(`/api/matches/${matchId}/join`, initData, { method: 'POST' }),
  matchInvite: (initData: string, matchId: string, friend_user_id: string) =>
    request<{ match_id: string; invited: boolean; already: boolean; status: string }>(
      `/api/matches/${matchId}/invite`, initData, {
        method: 'POST',
        body: JSON.stringify({ friend_user_id }),
      }),
  matchLink: (initData: string, matchId: string) =>
    request<MatchInviteLink>(`/api/matches/${matchId}/invite-link`, initData),
  matchStart: (initData: string, matchId: string) =>
    request<MatchView>(`/api/matches/${matchId}/start`, initData, { method: 'POST' }),
  matchSubmit: (initData: string, matchId: string, session_id: string) =>
    request<MatchView | MatchResultView>(`/api/matches/${matchId}/submit`, initData, {
      method: 'POST',
      body: JSON.stringify({ session_id }),
    }),
  matchFinalize: (initData: string, matchId: string) =>
    request<MatchResultView>(`/api/matches/${matchId}/finalize`, initData, { method: 'POST' }),
  matchCancel: (initData: string, matchId: string) =>
    request<{ match_id: string; status: string }>(`/api/matches/${matchId}/cancel`, initData, { method: 'POST' }),
  matchLeave: (initData: string, matchId: string) =>
    request<{ match_id: string; status: string }>(`/api/matches/${matchId}/leave`, initData, { method: 'POST' }),
  matchRematch: (initData: string, matchId: string) =>
    request<MatchView>(`/api/matches/${matchId}/rematch`, initData, { method: 'POST' }),
};

export function newClientGuessId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}
