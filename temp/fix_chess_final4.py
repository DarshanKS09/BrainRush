import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

out = []
i = 0
n = len(lines)

# We'll walk line by line; when we hit the malformed area around the duplicated header,
# skip until a safe anchor ("    // Main game screen") and emit a clean header.

safe_anchor = "    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n          <button onClick={onExit}"
anchors = []
start_idx = None
for idx in range(n-10):
    chunk = "\n".join(lines[idx:idx+9])
    if chunk.startswith("    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n          <button onClick={onExit}"):
        start_idx = idx
        break

if start_idx is None:
    # Fall back: find "    // Main game screen" and "    return (" and rebuild from there
    for idx in range(n):
        if lines[idx].rstrip() == "    // Main game screen":
            start_idx = idx
            break

if start_idx is None:
    sys.stdout.buffer.write(b"ERR: anchor not found\n")
    sys.exit(1)

# Emit lines before anchor as-is
out += lines[:start_idx]

# Emit the clean header block
clean_header = [
    "    // Main game screen",
    "    return (",
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
    "      </div>",
    "      <div className=\"flex justify-center\">",
]
out += clean_header

# Now skip original lines until we reach the same anchor "      <div className=\"flex justify-center\">"
j = start_idx + 1
while j < n and not lines[j].rstrip().startswith("      <div className=\"flex justify-center\">"):
    j += 1
if j == n:
    sys.stdout.buffer.write(b"ERR: flex justify-center anchor not found\n")
    sys.exit(2)

# Emit the rest from that anchor onward (including the anchor)
out += lines[j:]

io.open(p, 'w', encoding='utf-8').write("\n".join(out) + "\n")
sys.stdout.buffer.write(b"OK rebuilt\n")
