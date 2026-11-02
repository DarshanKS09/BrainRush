import io, sys

p = 'frontend/src/screens/ChessPlay.tsx'
lines = io.open(p, encoding='utf-8').read().splitlines()

clean = []
i = 0
n = len(lines)

# Pass 1: drop duplicate consecutive lines that look like duplicated headers
while i < n:
    cur = lines[i].rstrip()
    # If we see a duplicated "      <div className=\"space-y-3\">" followed immediately by
    # "      <div className=\"flex items-center justify-between\">" again, skip the second dup.
    if cur == "      <div className=\"space-y-3\">" and i+1 < n and lines[i+1].rstrip() == "      <div className=\"flex items-center justify-between\">":
        # keep first occurrence only if we already emitted the same sequence recently?
        if len(clean) >= 2 and clean[-1].rstrip() == "      <div className=\"space-y-3\">" and clean[-2].rstrip() == "        {/* Promotion pending notice */}":
            # This is a second occurrence inside promotion chooser; keep it but re-indent
            clean.append(lines[i])
            i += 1
            continue
        # skip until we reach the matching "      </div>" that closes the header block and then one more div close
        # Heuristic: skip lines until we emit a single clean header
        clean.append(lines[i])  # keep first <div space-y-3>
        i += 1
        # now skip until we find a "        </div>" then "      </div>" pattern
        depth = 0
        while i < n:
            r = lines[i].rstrip()
            if r == "        <div className=\"flex items-center justify-between\">":
                clean.append(lines[i]); i+=1; depth+=1; continue
            if r.startswith("          <button") or r.startswith("          <div") or r.startswith("            <span") or r.startswith("            <button") or r.startswith("            ↩") or r.startswith("            ✕"):
                clean.append(lines[i]); i+=1; continue
            if r.startswith("          <span") or r.startswith("            ←") or r.startswith("            ↩") or r.startswith("            ✕"):
                clean.append(lines[i]); i+=1; continue
            if r.startswith("          {game.difficulty") or r.startswith("          {game.playerColor") or r.startswith("            {game.difficulty") or r.startswith("            {game.playerColor"):
                clean.append(lines[i]); i+=1; continue
            if r == "          </div>" and depth>0:
                clean.append(lines[i]); i+=1; depth-=1; continue
            if r == "        </div>" and depth==0:
                clean.append(lines[i]); i+=1; break
            clean.append(lines[i]); i+=1
        continue

    clean.append(lines[i])
    i += 1

io.open(p, 'w', encoding='utf-8').write("\n".join(clean) + "\n")
sys.stdout.buffer.write(b"OK\n")
