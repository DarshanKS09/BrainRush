import io, sys
p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()
buf = io.StringIO()
for n in [320,325,330,333,336,338,340,342,345,350,353,400,405,410,417,420]:
    buf.write(f"--- {n} ---\n")
    buf.write(lines[n-1] + "\n")
    buf.write("--- end ---\n")
sys.stdout.buffer.write(buf.getvalue().encode('utf-8'))
