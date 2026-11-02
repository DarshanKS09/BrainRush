import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Identify the real function-end point and strip duplicated JSX tail.
# The legitimate last part of the file should be:
# ...    </div>\n  );\n}\n\n// Piece Unicode characters ...\n\nconst BLACK_PIECES ...\n};
# plus a small polyhedral dice helper.

# Strategy: find the function close "  );\n}\n" followed by "// Piece Unicode characters"
# There are two such places; keep the first and drop everything from the second
# "  );\n}\n" onward, then append a single cleaned tail.

tail_block = """  );
}

// Piece Unicode characters
const WHITE_PIECES: Record<string, string> = {
  king: '♔',
  queen: '♕',
  rook: '♖',
  bishop: '♗',
  knight: '♘',
  pawn: '♙',
};

const BLACK_PIECES: Record<string, string> = {
  king: '♚',
  queen: '♛',
  rook: '♜',
  bishop: '♝',
  knight: '♞',
  pawn: '♟',
};

// Small polyhedral dice helpers used by the legacy number-guessing minigame.
function rollSingleD6(): 1 | 2 | 3 | 4 | 5 | 6 {
  return ((Math.random() * 6) | 0) + 1;
}
"""

first_close = src.find("  );\n}\n\n// Piece Unicode characters")
if first_close == -1:
    sys.stdout.buffer.write(b"ERROR: could not find first legitimate close\n")
    sys.exit(2)

second_close = src.find("  );\n}\n\n// Piece Unicode characters", first_close + 10)
if second_close == -1:
    sys.stdout.buffer.write(b"ERROR: could not find duplicated close\n")
    sys.exit(3)

out = src[:first_close + len("  );\n}\n")] + tail_block
io.open(p, 'w', encoding='utf-8').write(out)
sys.stdout.buffer.write(b"OK\n")
