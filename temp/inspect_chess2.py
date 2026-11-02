import io, sys
p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()
buf = io.StringIO()
for n in [336,337,338,339,340,352,353,354,408,409,410,411,412,487,488,489,500,501,502,503,504,505,506,507,508]:
    buf.write(f"--- {n} ---\n")
    buf.write("\n".join(lines[n-1:n+1]) + "\n")
sys.stdout.buffer.write(buf.getvalue().encode('utf-8'))
