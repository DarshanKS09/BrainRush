import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Target the malformed area around line 338. It should be:
#              )})
#            <button ... Cancel
# But currently the file has an extra orphaned line causing the comma error.

# Pattern: after the promotion list closing </div> we have "              )})" then an
# indent mismatch causing "            <button" to be interpreted as attribute.
# We'll normalize that fragment.

bad_start = "              )})\n          </div>\n            <button\n              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}\n              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n            >\n              Cancel\n            </button>\n          </div>\n        </div>\n      );\n    }\n\n    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n        <button onClick={onExit}"
good_start = "              )})\n          </div>\n            <button\n              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}\n              className=\"mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95\"\n            >\n              Cancel\n            </button>\n          </div>\n        </div>\n      );\n    }\n\n    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n          <button onClick={onExit}"

idx = src.find(bad_start)
if idx == -1:
    # try a slightly different spacing variant
    bad_start = bad_start.replace("\n          <button", "\n        <button")
    good_start = good_start.replace("\n          <button", "\n        <button")
    idx = src.find(bad_start)

if idx == -1:
    sys.stdout.buffer.write(b"ERR: malformed fragment not found\n")
    sys.exit(1)

out = src[:idx] + good_start + src[idx + len(bad_start):]
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
