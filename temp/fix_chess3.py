import io, sys
p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

# drop duplicated tail block that starts with '// Small polyhedral dice helpers' appearing twice
out = []
seen_small_poly = 0
for line in lines:
    if line.strip() == '// Small polyhedral dice helpers used by the legacy number-guessing minigame.':
        seen_small_poly += 1
        if seen_small_poly > 1:
            continue
    out.append(line)

io.open(p,'w',encoding='utf-8').write("\n".join(out))
sys.stdout.buffer.write(b"OK\n")
