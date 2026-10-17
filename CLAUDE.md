# Working on weddings-dot-cl

Same voice and ground rules as `pitahorn/claude-rocky-pet` (see its CLAUDE.md):
Rocky voice, brief replies, ask before destructive actions, commit only when asked.

- Be polite to the Wayback Machine: one scraper at a time, keep `INTERVALO` (~12 requests/min). It blocks above ~15/min.
- `cache/` holds the raw pages (gzipped, git-ignored). Fix the parser and re-run — never re-download.
- `index.html` must keep working from a double-click (`file://`), so data ships as `data/*.js`, not JSON + fetch.
- Raw HTML and photos stay out of git. Photos live in R2 (`cache/r2.txt` lists uploaded vendors) or load as exact archive links; `.env` holds the R2 keys and is never committed.
