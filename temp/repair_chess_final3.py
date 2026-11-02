import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Locate the malformed area by finding a likely duplicated fragment near line 338.
# The fragment is:
#   "              )})\n          </div>\n            <button\n              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}\n              className=...\n            >\n              Cancel\n            </button>\n          </div>\n        </div>\n      );\n    }\n\n    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n        <button onClick={onExit}"

malfrag = (
    "              )})\n"
    "          </div>\n"
    "            <button\n"
    "              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}\n"
    "              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n"
    "            >\n"
    "              Cancel\n"
    "            </button>\n"
    "          </div>\n"
    "        </div>\n"
    "      );\n"
    "    }\n\n"
    "    // Main game screen\n"
    "    return (\n"
    "      <div className=\"space-y-3\">\n"
    "        <div className=\"flex items-center justify-between\">\n"
    "        <button onClick={onExit}"
)
idx = src.find(malfrag)
if idx == -1:
    sys.stdout.buffer.write(b"ERR: malformed fragment not found\n")
    sys.exit(1)

goodfrag = (
    "              )})\n"
    "          </div>\n"
    "            <button\n"
    "              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}\n"
    "              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n"
    "            >\n"
    "              Cancel\n"
    "            </button>\n"
    "          </div>\n"
    "        </div>\n"
    "      );\n"
    "    }\n\n"
    "    // Main game screen\n"
    "    return (\n"
    "      <div className=\"space-y-3\">\n"
    "        <div className=\"flex items-center justify-between\">\n"
    "          <button onClick={onExit}"
)
out = src[:idx] + goodfrag + src[idx + len(malfrag):]
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
