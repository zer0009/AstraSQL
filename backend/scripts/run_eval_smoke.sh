#!/usr/bin/env bash
# Nightly smoke: re-run the fixed 25-question set and gate against baseline.
set -euo pipefail
cd "$(dirname "$0")/.."
BASELINE="${BASELINE:-eval/results/run25.json}"
OUT="eval/results/smoke-$(date -u +%Y%m%dT%H%M%SZ).json"
MODEL="${MODEL:-gpt-5.6-luna}"

uv run python -m src.eval.pilot \
  --from-report "$BASELINE" \
  --model "$MODEL" \
  --reasoning-effort low \
  --interpretation-mode on \
  --validator-mode deterministic \
  --format-response false \
  --max-cost 1 \
  --out "$OUT"

uv run python scripts/eval_gate.py \
  --baseline "$BASELINE" \
  --candidate "$OUT" \
  --min-accuracy-delta -0.02 \
  --max-p95-latency-ratio 1.2 \
  --max-cost-ratio 1.2
