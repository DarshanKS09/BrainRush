import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

# Fix indentation around the malformed fragment at lines ~338-352.
# Target lines 336-345 (1-indexed) which currently look misaligned:
# 336: <span ...>
# 337: </button>
# 338: )})
# 339: </div>
# 340: <button ...
# We'll normalize that chunk.

# Operate by index ranges (1-indexed -> 0-indexed)
start = 335  # line 336
end   = 345  # line 345 inclusive

chunk = lines[start-1:end]

# Expected clean chunk (with correct indentation)
clean = [
    "                  <span className=\"block text-center text-4xl\">{p.unicode}</span>",
    "                  <span className=\"block text-xs mt-1 text-center\">{p.label}</span>",
    "                </button>",
    "              )})",
    "          </div>",
    "            <button",
    "              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}",
    "              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"",
    "            >",
    "              Cancel",
    "            </button>",
]
if len(chunk) < len(clean):
    # If file is shorter than expected, pad by appending the clean tail
    lines[start-1:end] = clean
else:
    lines[start-1:end] = clean

io.open(p, 'w', encoding='utf-8').write("\n".join(lines) + "\n")
sys.stdout.buffer.write(b"OK\n")
