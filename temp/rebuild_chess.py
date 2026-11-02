import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# 1) Collapse the duplicated main header block into one clean version.
dup_header_re = re.compile(
    r"    // Main game screen\n"
    r"    return \(\n"
    r"(      <div className=\"space-y-3\">\n"
    r"      <div className=\"flex items-center justify-between\">\n"
    r".*?"
    r"      </div>\n"
    r"      </div>\n"
    r"      </div>\n)+?"
    r"      <div className=\"flex justify-center\">",
    re.DOTALL
)

m = dup_header_re.search(src)
if not m:
    sys.stdout.buffer.write(b"ERR: dup header not found\n")
    sys.exit(1)

clean_header = (
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
    "      </div>\n"
    "      <div className=\"flex justify-center\">"
)

out = src[:m.start()] + clean_header + src[m.end():]

# 2) Fix malformed promotion chooser fragment: replace an orphaned "          </div>>" and
#    badly closed button sequence with a clean closing structure.
# We'll target a likely pattern: </div>> followed by "            <button\n ... Cancel"

promo_re = re.compile(
    r"          </div>>\n"
    r"            <button\n"
    r"              onClick=\\{\[^}]*setShowPromotionChooser\(false\); setPromotionPending\(null\);\}\[^}]*\)\n"
    r"              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n"
    r"            >\n"
    r"              Cancel\n"
    r"            </button>\n"
    r"          </div>\n"
    r"        </div>\n"
    r"      \)\;\n"
    r"    \}",
    re.DOTALL
)
pm = promo_re.search(out)
if not pm:
    sys.stdout.buffer.write(b"WARN: promo block not matched, continuing\n")
else:
    good_promo = (
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
        "    }"
    )
    out = out[:pm.start()] + good_promo + out[pm.end():]

io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
