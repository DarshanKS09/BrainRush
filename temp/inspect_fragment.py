import io, sys
p='frontend/src/screens/ChessPlay.tsx'
lines=io.open(p,encoding='utf-8').read().splitlines()
buf=io.StringIO()
for n in range(330,346):
    buf.write(f"{n:4d}: {lines[n-1]}\n")
sys.stdout.buffer.write(buf.getvalue().encode('utf-8'))
