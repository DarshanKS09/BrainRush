import io, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

# Remove orphaned lines 346-347 (0-indexed: 345-346) which are duplicate closing tags
# Lines are 1-indexed in the error; 346-347 corresponds to 0-indexed 345-346
del lines[345:347]  # remove the orphaned )}) and </div>

io.open(p, 'w', encoding='utf-8').write("\n".join(lines) + "\n")
sys.stdout.buffer.write(b"OK orphan removed\n")