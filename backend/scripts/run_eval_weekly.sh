#!/usr/bin/env bash
# Weekly 100-question Spider sample + paired compare vs prior weekly.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="eval/results/run100-$(date -u +%Y%m%dT%H%M%SZ).json"
MODEL="${MODEL:-gpt-5.6-luna}"
PRIOR="${PRIOR:-}"

uv run python -m src.eval.pilot \
  --dbs 10 \
  --per-db 10 \
  --model "$MODEL" \
  --reasoning-effort low \
  --format-response false \
  --max-cost 5 \
  --out "$OUT"

if [[ -n "$PRIOR" && -f "$PRIOR" ]]; then
  uv run python -m src.eval.pilot compare "$PRIOR" "$OUT"
  uv run python scripts/eval_gate.py \
    --baseline "$PRIOR" \
    --candidate "$OUT" \
    --min-accuracy-delta -0.03 \
    --max-p95-latency-ratio 1.25 \
    --max-cost-ratio 1.25
fi

echo "Wrote $OUT"
