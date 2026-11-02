import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Find the duplicated section manually by locating the first occurrence of the malformed
# "      <div className=\"space-y-3\">\n      <div className=\"flex items-center justify-between\">"
# that appears right after "    return (". We'll keep the first and drop the second.

marker = "    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n      <div className=\"flex items-center justify-between\">"
idx1 = src.find(marker)
if idx1 == -1:
    sys.stdout.buffer.write(b"ERR: first header not found\n")
    sys.exit(1)

idx2 = src.find(marker, idx1 + 10)
if idx2 == -1:
    sys.stdout.buffer.write(b"WARN: second header not found; attempting single repair\n")
    # Only one header present; still fix possible indentation issues at line ~338 region
    # Find the malformed fragment near line 338 by searching "              )})\n          </div>\n            <button"
    frag = "              )})\n          </div>\n            <button"
    fidx = src.find(frag)
    if fidx == -1:
        sys.stdout.buffer.write(b"ERR: malformed fragment not found\n")
        sys.exit(2)
    # Replace with clean fragment
    good_frag = "              )})\n          </div>\n            <button"
    out = src[:fidx] + good_frag + src[fidx + len(frag):]
    io.open(p, 'w', encoding='utf-8').write(out)
    sys.stdout.buffer.write(b"OK single\n")
    sys.exit(0)

# There are two headers; keep first, remove second up to the next "      <div className=\"flex justify-center\">"
end_marker = "      <div className=\"flex justify-center\">"
end_idx = src.find(end_marker, idx2)
if end_idx == -1:
    sys.stdout.buffer.write(b"ERR: end marker not found\n")
    sys.exit(2)

keep = src[:idx2] + src[end_idx:]
io.open(p, 'w', encoding='utf-8').write(keep)
sys.stdout.buffer.write(b"OK dup removed\n")
