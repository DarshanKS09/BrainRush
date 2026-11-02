import io, re, sys

p = 'frontend/src/screens/ChessPlay.tsx'
src = io.open(p, encoding='utf-8').read()

# 1) Normalize indentation: convert any leading 8+ spaces to 2-space based indentation in JSX regions.
# We'll do targeted regex replacements instead of full reformat.

repls = [
    # duplication: extra <div className="space-y-3"> at start of main return
    ("    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n      <div className=\"flex items-center justify-between\">",
     "    // Main game screen\n    return (\n      <div className=\"space-y-3\">\n        <div className=\"flex items-center justify-between\">"),

    # duplication: extra closing tags/buttons after Undo/Give up row
    ("        </div>\n          </button>\n        </div>\n      </div>\n\n      <div",
     "        </div>\n      </div>\n\n      <div"),

    # nested map closing broken indentation / duplicated parens
    # We expect:
    #               )
    #             )
    #          </div>
    # Replace occurrences like:
    #                );
    #              )
    #            )}
    #          </div>
    # with properly nested single closing sequence
    ("                );\n              )\n            )}\n          </div>",
     "                );\n              })\n            )}\n          </div>"),

    # Promotion chooser closing fragment broken: </div>> etc.
    ("          </div>>\n            <button",
     "          </div>\n            <button"),

    # Another likely broken close in promotion chooser: ")}            ))}"
    ("              )            )}\n          </div>",
     "              )})\n          </div>"),

    # Another broken nested close around promotion list items
    ("                <span\n                  key={i}\n                  className={`rounded-lg px-2 py-0.5 text-xs font-mono ${\n                    i % 2 === 0 ? 'bg-navy/50 text-slate-200' : 'bg-navy/30 text-slate-300'\n                  }`}\n              >\n                {i % 2 === 0 ? `${Math.floor(i / 2) + 1}. ` : ''}{move}\n              </span>\n            ))}\n          </div>",
     "                <span\n                  key={i}\n                  className={`rounded-lg px-2 py-0.5 text-xs font-mono ${\n                    i % 2 === 0 ? 'bg-navy/50 text-slate-200' : 'bg-navy/30 text-slate-300'\n                  }`}\n                >\n                  {i % 2 === 0 ? `${Math.floor(i / 2) + 1}. ` : ''}{move}\n                </span>\n              ))}\n            </div>"),

    # Duplicated status bar sections (two nearly identical status bars). Keep one.
    ("      {/* Status bar */}\n      <div className=\"flex items-center justify-between text-xs text-slate-400\">\n        <div className=\"flex items-center gap-2\">\n          <span className=\"w-3 h-3 rounded-full\" style={{ backgroundColor: getTurn() === 'white' ? '#fff' : '#000' }} />\n          <span>{getTurn()} to move</span>\n        </div>\n        {getMoveHistory().length === 0 ? (\n          <p className=\"text-sm text-slate-500 text-center py-2\">No moves yet</p>\n        ) : (\n          <div className=\"flex flex-wrap gap-1\">\n            {getMoveHistory().map((move, i) => (\n              <span\n                key={i}\n                className={`rounded-lg px-2 py-0.5 text-xs font-mono ${\n                  i % 2 === 0 ? 'bg-navy/50 text-slate-200' : 'bg-navy/30 text-slate-300'\n                }`}\n              >\n                {i % 2 === 0 ? `${Math.floor(i / 2) + 1}. ` : ''}{move}\n              </span>\n            ))}\n          </div>\n        )}\n      </div>\n\n      {/* Status bar */}",
     "      {/* Status bar */}"),

    # Duplicated restart/notice sections before final close
    ("      {/* Promotion pending notice */}\n      {promotionPending && !showPromotionChooser && (\n        <div className=\"rounded-xl bg-amber-500/20 p-3 text-center shadow-card\">\n          <p className=\"text-sm text-amber-300 font-semibold\">\n            Choose a piece to promote to:\n          </p>\n        </div>\n      )}\n\n      {/* Restart button */}\n      <div className=\"flex gap-2\">\n        <button\n          onClick={handleRestart}\n          disabled={busy}\n          className=\"flex-1 rounded-xl bg-panel py-2 text-xs font-bold text-slate-300 active:scale-95 disabled:opacity-50\"\n        >\n          ↻ Restart\n        </button>\n      </div>\n\n      <p className=\"text-[10px] text-center text-slate-500\">\n        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.\n      </p>\n    </div>\n  );\n}\n\n// Piece Unicode characters",
     "      {/* Promotion pending notice */}\n      {promotionPending && !showPromotionChooser && (\n        <div className=\"rounded-xl bg-amber-500/20 p-3 text-center shadow-card\">\n          <p className=\"text-sm text-amber-300 font-semibold\">\n            Choose a piece to promote to:\n          </p>\n        </div>\n      )}\n\n      {/* Restart button */}\n      <div className=\"flex gap-2\">\n        <button\n          onClick={handleRestart}\n          disabled={busy}\n          className=\"flex-1 rounded-xl bg-panel py-2 text-xs font-bold text-slate-300 active:scale-95 disabled:opacity-50\"\n        >\n          ↻ Restart\n        </button>\n      </div>\n\n      <p className=\"text-[10px] text-center text-slate-500\">\n        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.\n      </p>\n    </div>\n  );\n}\n\n// Piece Unicode characters"),

    # Deduplicate duplicated footer paragraphs and tail close fragments
    ("        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.\n      </p>\n    </div>\n  );\n}\n\n// Piece Unicode characters\nconst WHITE_PIECES: Record<string, string> = {\n  king: '♔',\n  queen: '♕',\n  rook: '♖',\n  bishop: '♗',\n  knight: '♘',\n  pawn: '♙',\n};\n\nconst BLACK_PIECES: Record<string, string> = {\n  king: '♚',\n  queen: '♛',\n  rook: '♜',\n  bishop: '♝',\n  knight: '♞',\n  pawn: '♟',\n};\n\n// Small polyhedral dice helpers used by the legacy number-guessing minigame.\nfunction rollSingleD6(): 1 | 2 | 3 | 4 | 5 | 6 {\n  return ((Math.random() * 6) | 0) + 1;\n}\n\n        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.\n      </p>\n    </div>\n  );\n}\n\n// Piece Unicode characters",
     "        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.\n      </p>\n    </div>\n  );\n}\n\n// Piece Unicode characters"),
]

changed = False
for a,b in repls:
    if a in src:
        src = src.replace(a,b,1)
        changed = True
    else:
        sys.stdout.buffer.write(f"WARN not found:\n{a!r}\n\n".encode('utf-8'))

if not changed:
    sys.stdout.buffer.write(b"NO CHANGES MADE\n")
    sys.exit(0)

io.open(p,'w',encoding='utf-8').write(src)
sys.stdout.buffer.write(b"OK CHANGES\n")
