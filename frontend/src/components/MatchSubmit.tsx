import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { WebAppContext } from '../telegram';

/** Auto-submits one finished solo session to a match seat (idempotent). */
export function MatchSubmitBanner({
  ctx,
  matchId,
  sessionId,
  onBackToMatch,
}: {
  ctx: WebAppContext;
  matchId: string;
  sessionId: string;
  onBackToMatch: () => void;
}) {
  const [status, setStatus] = useState<'sending' | 'done' | 'error'>('sending');
  const [message, setMessage] = useState('');
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    let cancelled = false;
    api
      .matchSubmit(ctx.initData, matchId, sessionId)
      .then(() => {
        if (!cancelled) {
          setStatus('done');
          setMessage('Result submitted to the match ✓');
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setStatus('error');
          setMessage(e.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ctx.initData, matchId, sessionId]);

  const retry = () => {
    sent.current = false;
    setStatus('sending');
    setMessage('');
    // Re-trigger by toggling: simplest is a direct call here.
    api
      .matchSubmit(ctx.initData, matchId, sessionId)
      .then(() => {
        sent.current = true;
        setStatus('done');
        setMessage('Result submitted to the match ✓');
      })
      .catch((e: Error) => {
        sent.current = false;
        setStatus('error');
        setMessage(e.message);
      });
  };

  return (
    <div className="mt-3 rounded-2xl bg-navy p-3 text-center" role="status">
      {status === 'sending' && <p className="text-sm text-slate-300">Submitting to match…</p>}
      {status === 'done' && <p className="text-sm font-bold text-emerald-300">{message}</p>}
      {status === 'error' && (
        <>
          <p className="text-sm text-amber-300">Submit failed: {message}</p>
          <button onClick={retry} className="mt-1 text-xs font-bold text-neon-cyan">
            Retry submit
          </button>
        </>
      )}
      <button
        onClick={onBackToMatch}
        className="mt-2 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2 text-sm font-bold text-white"
      >
        ← Back to match
      </button>
    </div>
  );
}
