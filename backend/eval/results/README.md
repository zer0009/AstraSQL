# Eval result artifacts

JSON files in this directory are **developer artifacts** from local / CI pilot
runs. They may be committed for offline analysis (accuracy diffs, failure
mining, ablation comparisons).

- Prefer small reports (`held_out*.json`, `bird*.json`, compare summaries).
- Large benchmark source data (Spider / BIRD SQLite DBs, zips) stays under
  `backend/eval/benchmarks/data/` and is gitignored — do not commit those.
- Generated mining reports such as `offline_diff_report.json` are also fine to
  keep here when useful for review.

Re-run pilots with `uv run python -m src.eval.pilot ...` from `backend/`.
