import io, sys
p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()
buf = io.StringIO()
for n in [330,345,350,356,410,440,485,500,525,545,560]:
    buf.write(f"--- {n} ---\n")
    buf.write("\n".join(lines[n-1:n+3]) + "\n")
sys.stdout.buffer.write(buf.getvalue().encode('utf-8'))
