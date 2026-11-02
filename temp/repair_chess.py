import io, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

# Normalize the duplicated/orphan header lines around 338-354.
# Build a normalized region by deduplicating and fixing indentation.

out = []
i = 0
n = len(lines)

# We'll reconstruct from line 1 up to the problematic region, then emit
# a clean reconstructed block, then the rest unchanged.

def emit_line(idx, indent=0):
    out.append((" " * indent) + lines[idx].lstrip())

# Find start of duplicated header block: "// Main game screen"
main_start = None
for idx in range(n):
    if lines[idx].rstrip() == "    // Main game screen":
        main_start = idx
        break

if main_start is None:
    sys.stdout.buffer.write(b"ERR no main start\n")
    sys.exit(2)

# Find the first "return (" after main_start
ret_idx = None
for idx in range(main_start+1, n):
    if lines[idx].rstrip() == "    return (":
        ret_idx = idx
        break
if ret_idx is None:
    sys.stdout.buffer.write(b"ERR no return\n")
    sys.exit(3)

# Emit everything up to and including main_start
for idx in range(main_start+1):
    out.append(lines[idx])

# Emit clean header block
hdr = [
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
]
for h in hdr:
    out.append(h)

# Now skip the original duplicated header lines until we find the first
# "      <div className=\"flex justify-center\">" after the return
j = ret_idx + 1
while j < n:
    if lines[j].rstrip() == "      <div className=\"flex justify-center\">":
        break
    j += 1
if j == n:
    sys.stdout.buffer.write(b"ERR no flex justify-center\n")
    sys.exit(4)

# Emit the rest of the file from that div onward
for idx in range(j, n):
    out.append(lines[idx])

io.open(p, 'w', encoding='utf-8').write("\n".join(out) + "\n")
sys.stdout.buffer.write(b"OK\n")
