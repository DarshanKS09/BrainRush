import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Locate the duplicated header block by searching for the malformed pattern:
# "      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n        <button onClick={onExit}"
mal = "      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n        <button onClick={onExit}"
idx = src.find(mal)
if idx == -1:
    sys.stdout.buffer.write(b"ERR: malformed anchor not found\n")
    sys.exit(1)

# Find the end of this malformed block: next occurrence of "      <div className=\"flex justify-center\">"
end = src.find("      <div className=\"flex justify-center\">", idx)
if end == -1:
    sys.stdout.buffer.write(b"ERR: end anchor not found\n")
    sys.exit(1)

good = (
    "      <div className=\"space-y-3\">\n"
    "        <div className=\"flex items-center justify-between\">\n"
    "          <button onClick={onExit} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95\" aria-label=\"Back to lobby\">\n"
    "            ← Lobby\n"
    "          </button>\n"
    "          <div className=\"flex items-center gap-2\">\n"
    "            <span className=\"rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan\">\n"
    "              {game.difficulty.charAt(0).toUpperCase() + game.difficulty.slice(1)}\n"
    "            </span>\n"
    "            <span className=\"rounded-full bg-panel px-3 py-1 text-xs font-bold text-slate-400\">\n"
    "              {game.playerColor} · {getTurn()} to move\n"
    "            </span>\n"
    "          </div>\n"
    "          <div className=\"flex items-center gap-2\">\n"
    "            <button onClick={handleUndo} disabled={busy || game.position.halfMoves < 2} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95 disabled:opacity-40\" aria-label=\"Undo\">\n"
    "              ↩ Undo\n"
    "            </button>\n"
    "            <button onClick={cancel} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95\" aria-label=\"Cancel game\">\n"
    "              ✕ Give up\n"
    "            </button>\n"
    "          </div>\n"
    "        </div>\n"
    "      </div>\n"
    "      <div className=\"flex justify-center\">"
)
out = src[:idx] + good + src[end:]
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
