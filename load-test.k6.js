/**
 * BrainRush Load Test (k6)
 *
 * Tests API endpoints under progressive load. Designed to run against a
 * local or staging backend — NEVER against production without explicit
 * authorization.
 *
 * Usage:
 *   k6 run load-test.k6.js
 *
 * Environment variables:
 *   BASE_URL        - Backend API base URL (default: http://localhost:8000)
 *   INIT_DATA       - Valid Telegram initData string for authenticated requests
 *   VUS             - Virtual users (default: 10)
 *   DURATION        - Test duration (default: 30s)
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
export const INIT_DATA = __ENV.INIT_DATA || '';
export const VUS = parseInt(__ENV.VUS || '10');
export const DURATION = __ENV.DURATION || '30s';

// Custom metrics
const errorRate = new Counter('errors');
const apiLatency = new Trend('api_latency_ms');

function headers(initData = INIT_DATA) {
  return {
    'Content-Type': 'application/json',
    'X-Telegram-Init-Data': initData,
  };
}

// Track scenario counts for reporting
const requestsCounter = new Counter('total_requests');

// Test data
const GAME_TYPES = ['number_guessing', 'color_sequence', 'reflex_rush', 'perfect_second'];
const DIFFICULTIES = ['easy', 'medium', 'hard'];

export const options = {
  stages: [
    { duration: '10s', target: 10 },   // ramp up to 10
    { duration: '10s', target: 25 },   // ramp up to 25
    { duration: '10s', target: 50 },   // ramp up to 50
    { duration: '10s', target: 100 },  // ramp up to 100
    { duration: '30s', target: 100 },  // hold at 100
    { duration: '10s', target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'], // 95th percentile under 2s
    http_req_failed: ['rate<0.05'],     // error rate under 5%
    errors: ['count<50'],               // fewer than 50 custom errors
  },
};

export function setup() {
  // Verify backend is reachable
  const res = http.get(`${BASE_URL}/health`);
  if (res.status !== 200 && res.status !== 503) {
    // 503 means DB unreachable but server is up; that's still "reachable"
    throw new Error(`Backend not reachable at ${BASE_URL}: ${res.status}`);
  }
  return { baseUrl: BASE_URL, initData: INIT_DATA };
}

export default function (data) {
  const { baseUrl, initData } = data;
  const hdrs = headers(initData);

  // 1. Health check (unauthenticated)
  let res = http.get(`${baseUrl}/health`);
  check(res, { 'health is 200 or 503': (r) => r.status === 200 || r.status === 503 });
  apiLatency.add(res.timings.duration);

  // 2. Games catalog (unauthenticated, cacheable)
  res = http.get(`${baseUrl}/api/games`);
  check(res, { 'games catalog is 200': (r) => r.status === 200 });
  apiLatency.add(res.timings.duration);

  // Skip authenticated tests if no initData provided
  if (!initData) {
    sleep(1);
    return;
  }

  // 3. Dashboard (authenticated)
  res = http.get(`${baseUrl}/api/me`, { headers: hdrs });
  check(res, { 'dashboard is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 4. History (authenticated, paginated)
  res = http.get(`${baseUrl}/api/history?limit=20&offset=0`, { headers: hdrs });
  check(res, { 'history is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 5. Leaderboard (authenticated, rate-limited)
  res = http.get(`${baseUrl}/api/leaderboard?limit=20&offset=0`, { headers: hdrs });
  check(res, { 'leaderboard is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 6. Start a game session (authenticated)
  res = http.post(`${baseUrl}/api/sessions`, JSON.stringify({
    game_type: 'number_guessing',
    difficulty: 'hard',
  }), { headers: hdrs });
  check(res, { 'start session is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 7. Referral stats (authenticated)
  res = http.get(`${baseUrl}/api/referrals/stats`, { headers: hdrs });
  check(res, { 'referral stats is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 8. Friends list (authenticated)
  res = http.get(`${baseUrl}/api/friends`, { headers: hdrs });
  check(res, { 'friends list is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  // 9. My matches (authenticated)
  res = http.get(`${baseUrl}/api/matches/mine?limit=20&offset=0`, { headers: hdrs });
  check(res, { 'my matches is 200': (r) => r.status === 200 });
  if (res.status !== 200) errorRate.add(1);
  apiLatency.add(res.timings.duration);

  sleep(1);
}

export function teardown(data) {
  // No cleanup needed for read-only tests
}
