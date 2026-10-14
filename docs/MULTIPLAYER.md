# BrainRush Multiplayer

One shared match engine for every game. Players compete on their own phones:
each seat links **one finished solo session** (existing game rules unchanged),
and the backend ranks the validated scores.

## Lifecycle

```
create (lobby) → join (lobby) → host starts (active) → each player plays solo
→ submit session (seat) → all finished OR deadline → completed → rematch (new match)
```

- **Lobby**: host seated immediately. Joins via share-link token (`POST
  /api/matches/join`), human-readable room code (`POST
  /api/matches/join-by-code`), or known id (`POST /api/matches/{id}/join`).
  All three are idempotent — repeat joins return the current view. Room codes
  are manual-entry conveniences, never authorization secrets (identity always
  comes from verified `initData`); only share-link tokens go into URLs.
- **Start**: host-only, needs minimum seats (duel 2, ffa 3, tournament 5).
  Server timestamps are authoritative (`started_at`, `deadline`).
- **Play**: `MatchDetail → Play my round` starts a normal solo session at the
  match difficulty. On finish, the client auto-submits the `session_id` once
  (`MatchSubmitBanner`); retries replay the current view.
- **Submit validation** (server-side): session owned by caller, `completed`,
  same `game_type`, started after the match, attached to no other match. One
  session per seat; a *different* session is rejected.
- **Finalize**: automatic on read/submit when all seats finished or the
  deadline passed; any participant may also `POST …/finalize`. Idempotent —
  completed matches return stored results.
- **Rematch**: always a **new** match (same settings); prior participants are
  auto-*invited*, never auto-joined, so nobody reopens an old match by
  accident.
- **Stale handling**: lobbies past `MATCH_LOBBY_TTL_HOURS` (default 24) expire
  on read/list; invite tokens expire after `MATCH_INVITE_TTL_DAYS` (default 7);
  disconnects are non-blocking (presence is advisory `online` flags, 90 s
  window); page refresh/backgrounding just re-polls (`visibilitychange` +
  `focus` refresh, 3 s interval).

## Modes

| Mode | Min | Default max | Rule |
|---|---|---|---|
| `duel` | exactly 2 | 2 | exactly 2 to start; winner = game scoring |
| `ffa` | 3 | 8 | everyone plays solo; no one blocks anyone |
| `tournament` | 5 | 16 | shared timed match, ranked 1st…last |

Host may raise `max_players` up to 32 (`ABSOLUTE_MAX_PLAYERS`).

## Abandonment rule (explicit)

Unfinished seats at finalization **share the rank after all finished seats**
(a did-not-finish tie) with **0 XP**. No score is invented. Active matches
cannot be left formally — the seat simply counts as abandoned.

## Per-game adapters (`src/brainrush/game/multiplayer.py`)

| Game | Score | Higher wins | Tie-break |
|---|---|---|---|
| Number Guessing | attempts used | no (fewer tries) | earlier finish; private guesses never exposed |
| Color Sequence | levels completed | yes | earlier finish |
| Reflex Rush | points | yes | lower `avg_ms`, then earlier finish |
| Perfect Second | timing error (ms) | no (smaller error) | exact measured error, then earlier finish |

`rank_participants` sorts by (score direction, tie-break, user id) and assigns
**dense ranks** — equal keys share a rank; a remaining tie is never broken
arbitrarily.

## Rewards (configurable, separate economy)

- `MATCH_COMPLETION_XP` (default 10) per finished seat + `MATCH_WIN_BONUS`
  (default 10) for rank 1 (shared on ties). Each granted **at most once per
  user per match** via the `match_rewards` ledger (`UNIQUE(match_id, user_id,
  kind)` + `ON CONFLICT DO NOTHING`).
- `MATCH_DAILY_XP_CAP` (default 500/UTC day) bounds farming; each seat's
  budget = cap − already-credited-today.
- Match games **never** touch `games_played`/`wins`/`losses`/streaks/daily
  activity, the solo history feed, or the XP leaderboard ordering beyond the
  XP itself. Match history lives on `matches`/`match_participants`
  (`GET /api/matches/mine`); referral rewards are independent.
- No XP for opening links, joining lobbies, or submitting twice.

## Security

- Telegram `initData` verified server-side on every call; identity comes only
  from the verified user id.
- Non-participants get `404` on every match read/write (no existence leak).
- Only the host invites/starts/cancels; only friends can be invited (by user
  id); lobby-only invites; capacity + expiry enforced server-side.
- Clients never supply scores, XP, winners, or timestamps — only a
  `session_id` pointing at a server-validated finished solo game. Private
  state (secrets, others' guesses) never enters match views.
- State transitions are guarded (`lobby→active→completed`, `lobby→
  cancelled/expired`); concurrent joins collapse on
  `UNIQUE(match_id, user_id)`; concurrent rewards collapse on the ledger.

## Invitations / Telegram links

- `GET /api/matches/{id}/invite-link` returns `{token, link}`. `link` follows
  the configured bot: `https://t.me/<bot>/<app>?startapp=<token>` (named app)
  or `https://t.me/<bot>?startapp=<token>` (main app); `link` is `null` until
  `TELEGRAM_BOT_USERNAME` is set — the token always works.
- Tokens are `m-` + 24 urlsafe chars (cryptographically random). The `m-`
  prefix distinguishes them from referral codes (alphanumeric only) in
  `startapp` params. No secrets, DB ids, or scores in URLs.
- In-app: lobby shows pending invites (`GET /api/matches/invites`); friend
  invites are host-only, friends-only, idempotent. No proactive bot DMs are
  sent (no send path exists in the bot architecture).

## Adding a new game (e.g. Crash Predictor)

1. Add a `MultiplayerSpec` to `REGISTRY` in `game/multiplayer.py`: game id,
   supported modes, `higher_is_better`, `match_minutes`, and a deterministic
   `tiebreak_key`.
2. Keep the game's solo finish flow writing a validated `game_sessions` +
   `game_results` row with a numeric `score`. The match layer only links
   finished solo sessions — no new endpoints needed.
3. Define the game's authoritative rules first (shared round/outcome for
   Crash Predictor must be server-drawn; clients submit *predictions*, never
   outcomes), then map the outcome to `score`.
4. Inherited automatically: lobbies, invitations, share links, sync,
   validation, ranking, rewards, history, rematch, and cleanup.

## Shared round targets (Perfect Second)

Games whose round must be identical for every seat override
`MultiplayerSpec.shared_target_ms(match_id, difficulty)` with a
deterministic derivation (Perfect Second: `SHA-256(game, match id,
difficulty)` mapped onto the difficulty's target grid). The flow reuses
existing infrastructure — no duplicate match backend:

- Solo start accepts optional `match_id` (`POST /api/sessions`). The server
  requires an active match, caller membership, and equal game/difficulty,
  then resolves the shared target instead of rolling a fresh one.
- Match views expose the public `target_ms` (it is visible during attempts
  by design).
- Match submit rejects sessions whose stored target differs from the
  match's (`409`), so a foreign solo attempt can never score a seat.
- Timing fairness mirrors Reflex Rush: each player runs their own
  monotonic clock; the server validates bounds + target + membership +
  one-submit-per-seat, and the match deadline bounds the round.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `MATCH_COMPLETION_XP` | 10 | XP per finished seat |
| `MATCH_WIN_BONUS` | 10 | XP for rank 1 |
| `MATCH_DAILY_XP_CAP` | 500 | match XP per user per UTC day |
| `MATCH_LOBBY_TTL_HOURS` | 24 | unstarted lobby lifetime |
| `MATCH_INVITE_TTL_DAYS` | 7 | share-token lifetime |
| `MATCH_DEFAULT_MINUTES` | 60 | deadline fallback |
| `TELEGRAM_BOT_USERNAME` / `MINIAPP_SHORT_NAME` | empty | share-link host |
