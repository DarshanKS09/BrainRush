import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Locate the malformed duplication starting at the duplicated header fragment around
// "    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n      <div className=\"flex items-center justify-between\">"
# and ending right before "      <div className=\"flex justify-center\">"

pat = re.compile(
    r"    // Main game screen\n"
    r"    return \([^}]*\n"
    r"      <div className=\"space-y-3\">\n"
    r"      <div className=\"flex items-center justify-between\">.*?// Main game screen",
    re.DOTALL
)

m = pat.search(src)
if not m:
    sys.stdout.buffer.write(b"ERR: malformed block not found\n")
    sys.exit(1)

good = (
    "    // Main game screen\n"
    "    return (\n"
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
)

out = src[:m.start()] + good
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
