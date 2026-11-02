import io, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

# Find first occurrence of the duplicated malformed block: a line equal to
# "      <div className=\"flex items-center justify-between\">" immediately after
#   "      <div className=\"space-y-3\">"
start = None
for i in range(len(lines)-1):
    if lines[i].rstrip() == "      <div className=\"space-y-3\">" and lines[i+1].rstrip() == "      <div className=\"flex items-center justify-between\">":
        start = i
        break

if start is None:
    sys.stdout.buffer.write(b"ERR: dup header start not found\n")
    sys.exit(1)

# Find the end marker: next "      <div className=\"flex justify-center\">"
end = None
for j in range(start+1, len(lines)):
    if lines[j].rstrip() == "      <div className=\"flex justify-center\">":
        end = j
        break

if end is None:
    sys.stdout.buffer.write(b"ERR: end marker not found\n")
    sys.exit(2)

good_header = [
    "      <div className=\"space-y-3\">",
    "        <div className=\"flex items-center justify-between\">",
    "          <button onClick={onExit} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95\" aria-label=\"Back to lobby\">",
    "            ← Lobby",
    "          </button>",
    "          <div className=\"flex items-center gap-2\">",
    "            <span className=\"rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan\">",
    "              {game.difficulty.charAt(0).toUpperCase() + game.difficulty.slice(1)}",
    "            </span>",
    "            <span className=\"rounded-full bg-panel px-3 py-1 text-xs font-bold text-slate-400\">",
    "              {game.playerColor} · {getTurn()} to move",
    "            </span>",
    "          </div>",
    "          <div className=\"flex items-center gap-2\">",
    "            <button onClick={handleUndo} disabled={busy || game.position.halfMoves < 2} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95 disabled:opacity-40\" aria-label=\"Undo\">",
    "              ↩ Undo",
    "            </button>",
    "            <button onClick={cancel} className=\"rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95\" aria-label=\"Cancel game\">",
    "              ✕ Give up",
    "            </button>",
    "          </div>",
    "        </div>",
]

before = lines[:start]
after = lines[end:]
out = before + good_header + after
io.open(p, 'w', encoding='utf-8').write("\n".join(out) + "\n")
sys.stdout.buffer.write(b"OK\n")
