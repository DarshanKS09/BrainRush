import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# Find the duplicated header anchor:
# "    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">\n        <button onClick={onExit}"
# There might be one clean and one malformed; we want to drop the malformed one and ensure only one clean header.

clean_header_anchor = (
    "    // Main game screen\n"
    "    return (\n"
    "      <div className=\"space-y-3\">\n"
    "        <div className=\"flex items-center justify-between\">\n"
    "          <button onClick={onExit}"
)
malformed_anchor = (
    "    // Main game screen\n"
    "    return (\n"
    "      <div className=\"space-y-3\">\n"
    "        <div className=\"flex items-center justify-between\">\n"
    "        <button onClick={onExit}"
)

idx_clean = src.find(clean_header_anchor)
idx_mal  = src.find(malformed_anchor)

# If malformed exists and occurs before the clean one, remove it.
if idx_mal != -1 and (idx_clean == -1 or idx_mal < idx_clean):
    end_marker = "      <div className=\"flex justify-center\">"
    end_idx = src.find(end_marker, idx_mal)
    if end_idx == -1:
        sys.stdout.buffer.write(b"ERR: end marker not found after malformed\n")
        sys.exit(1)
    # remove from idx_mal to end_idx, keep end_idx
    out = src[:idx_mal] + src[end_idx:]
    io.open(p, 'w', encoding='utf-8').write(out)
    sys.stdout.buffer.write(b"OK removed malformed\n")
    sys.exit(0)

# If no malformed, ensure only one clean header exists (remove any second)
if idx_clean != -1:
    second_clean = src.find(clean_header_anchor, idx_clean + 10)
    if second_clean != -1:
        end_marker = "      <div className=\"flex justify-center\">"
        end_idx = src.find(end_marker, second_clean)
        if end_idx == -1:
            sys.stdout.buffer.write(b"ERR: end marker not found after second clean\n")
            sys.exit(1)
        out = src[:second_clean] + src[end_idx:]
        io.open(p, 'w', encoding='utf-8').write(out)
        sys.stdout.buffer.write(b"OK removed duplicate clean\n")
        sys.exit(0)

sys.stdout.buffer.write(b"OK nothing to remove\n")
