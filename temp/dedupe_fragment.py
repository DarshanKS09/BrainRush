import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Match the duplicated malformed fragment that starts at:
#   "              )})\n          </div>\n            <button\n              onClick={() => { setShowPromotionChooser(false); ..."
# and ends right before the clean header "    // Main game screen\n    return ("

pat = re.compile(
    r"              \}\)\)\n"
    r"          </div>\n"
    r"            <button\n"
    r"              onClick=\{\[\s\S]*?setShowPromotionChooser\(false\); setPromotionPending\(null\);\}\n"
    r"              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n"
    r"            >\n"
    r"              Cancel\n"
    r"            </button>\n"
    r"          </div>\n"
    r"        </div>\n"
    r"      \)\;\n"
    r"    \}\n"
    r"\n"
    r"    // Main game screen\n"
    r"    return \(\n"
    r"      <div className=\"space-y-3\">\n"
    r"        <div className=\"flex items-center justify-between\">\n"
    r"        <button onClick=\{onExit\}",
    re.DOTALL
)
m = pat.search(src)
if not m:
    sys.stdout.buffer.write(b"ERR: dup fragment not found\n")
    sys.exit(1)

replacement = (
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
out = src[:m.start()] + replacement + src[m.end():]
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
