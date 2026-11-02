import io, re, sys
p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()
# Look for duplicate tails
tails = {}
tail_re = re.compile(r"// Piece Unicode characters")
idxs = [i for i,l in enumerate(lines) if tail_re.search(l)]
buf = io.StringIO()
buf.write("tail markers at lines (1-indexed):\n")
for i in idxs:
    buf.write(f"{i+1}: {lines[i]}\n")
buf.write("\nFrom each tail marker, show next 12 lines:\n")
for i in idxs:
    buf.write(f"--- tail marker at {i+1} ---\n")
    buf.write("\n".join(lines[i:i+12]) + "\n")

sys.stdout.buffer.write(buf.getvalue().encode('utf-8'))
