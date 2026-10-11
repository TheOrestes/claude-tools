# Claude Usage Widget

A minimal always-on-top desktop widget for Windows 11 showing how much of the
current Claude usage window you have burned through, when it resets, and how
that usage splits across models.

```
  C L A U D E   U S A G E            resets 2h37m
  23%  22.0M
  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  opus 22.0M
  ▁▁▁▁▁▁▁▁▁▁▁▂▄▁█▂▅▁▁▁▁▁▁▁
  today 81.0M                             opus 100%
```

- **Header** — what this is, and the countdown to the window reset.
- **Headline** — percentage of the current 5-hour window used, and tokens in it. Clay under 60%, amber past 60%, red past 85%.
- **Bar** — the filled part is segmented by model, so the mix is visible in the
  same bar as the total.
- **Legend** — the top three models in this window, by tokens.
- **Sparkline** — today, hour by hour (00:00–23:00 local); the current hour is
  highlighted. This is the consumption-pattern view.
- **Footer** — tokens used today and each model's share of the day.

## Run it

Double-click `ClaudeUsage.exe`. It bundles Python and the fonts, so nothing else
needs to be installed. `config.json` and `state.json` are read from beside the exe.

**Start with Windows**: press `Win+R`, run `shell:startup`, and drop a *shortcut*
to `ClaudeUsage.exe` there (a shortcut, not a copy -- the settings live next to the exe).

**From source**: `pythonw widget.py` (standard library only).
**Rebuild the exe** after editing the code:

```
python -m PyInstaller --onefile --noconsole --name ClaudeUsage --add-data "fonts;fonts" --distpath . widget.py
```

## Controls

| Action | Result |
| --- | --- |
| Drag with left button | Move it; the position is remembered |
| Double-click | Collapse to a single line, and back |
| Right-click | Refresh, set budget, auto-calibrate, zoom, opacity, theme, quit |
| `Esc` | Quit |

## Where the numbers come from

Claude Code appends every assistant response to a JSONL transcript under
`~/.claude/projects/`, including a `usage` block with input, output, cache-read,
and cache-write tokens plus the model. The widget tails those files
incrementally (a refresh costs a few milliseconds after the first read) and
de-duplicates by message id, since one response can be logged more than once.

Usage windows are reconstructed the way Claude's own 5-hour windows work: a
window opens on the first message after a gap, anchored to the top of that hour,
and closes 5 hours later.

## About the percentage

Anthropic does not publish your remaining quota anywhere on disk, so the
percentage is measured against a **budget you set**, not against a number read
back from the server. Tokens are weighted by list API price so that Opus counts
roughly 5x a Sonnet token and cache reads count a tenth of fresh input — that
weighting mirrors how the plans themselves value the models, which a raw token
count does not.

`config.json`:

| Key | Meaning |
| --- | --- |
| `font_family` | Any installed family, or a bundled one; falls back to Segoe UI if missing |
| `budget_usd_per_window` | API-equivalent spend that counts as 100% of one 5-hour window |
| `auto_calibrate` | Raise the budget to your highest observed window, so the bar self-tunes |
| `refresh_seconds` | Poll interval (default 15) |
| `opacity` | 0.5–1.0 |
| `scale` | 0 follows display DPI; set e.g. `1.5` to force a size |
| `zoom` | Extra size multiplier (0.75-2.0), set from the right-click menu |
| `theme` | Claude, Midnight, Graphite, Forest, Dracula or Amber |

With `auto_calibrate` on, run normally for a few days: the busiest window you
ever complete becomes the reference for 100%. To calibrate deliberately, check
`/usage` in Claude Code when the widget reads some percentage, then set
`budget_usd_per_window` so the two line up.

## Files

| File | Purpose |
| --- | --- |
| `usage.py` | Transcript parsing, pricing, window and daily aggregation |
| `widget.py` | The tkinter widget |
| `ClaudeUsage.exe` | Built from `widget.py` with PyInstaller |
| `config.json` | Settings (above) |
| `state.json` | Window position and compact/expanded, written automatically |
| `fonts/` | Bundled Space Grotesk (Regular/Medium/Bold) and its OFL license |

## Typeface

The widget is set in [Space Grotesk](https://github.com/floriankarsten/space-grotesk).
The static TTFs are bundled in `fonts/` and registered with `AddFontResourceEx` under
`FR_PRIVATE` at startup, so they are visible to this process only — nothing is
installed into Windows and there is nothing to uninstall. If the files are removed
or the family fails to load, the widget silently falls back to Segoe UI. Set
`font_family` in `config.json` to use anything else you have installed.
Space Grotesk is licensed under the SIL Open Font License 1.1 (`fonts/OFL.txt`).
