# 25-question Spider run — results and improvement options

Measured on values-only denotation match (Spider-style). Margin on n=25 is wide (~±15–20 pp); treat as a direction.

Artifacts:

- `run25.json` — primary run
- `run25-variance.json` — same question IDs re-run
- `rescore-*.json` — free re-score of the 5-question pilot
- Fixed question IDs are in each report’s `question_ids` field

## Scores

| Metric | Run 1 | Variance re-run |
|--------|------:|----------------:|
| Values-only | **14/25 (56%)** | **16/25 (64%)** |
| Strict (column names) | 11/25 (44%) | 13/25 (52%) |
| Question cost | $0.046 | $0.045 |
| Question time | 389 s (~15.6 s/q) | 416 s |
| Schema-linking full recall | 25/25 (100%) | 25/25 |
| Per-id agreement | — | 23/25 (2 flips: clarification → answer) |

Pilot rescore (no LLM): **4/5 (80%)** values-only vs **2/5 (40%)** strict — old scorer under-reported.

### By hardness (run 1, values-only)

| Hardness | Score |
|----------|------:|
| easy | 6/7 (86%) |
| medium | 5/10 (50%) |
| hard | 2/5 (40%) |
| extra | 1/3 (33%) |

### By database (run 1, values-only)

| DB | Score |
|----|------:|
| concert_singer | 4/5 (80%) |
| course_teach | 3/5 (60%) |
| pets_1 | 3/5 (60%) |
| orchestra | 3/5 (60%) |
| network_1 | 1/5 (20%) |

## Failure mix (run 1)

| Label | Count | Notes |
|-------|------:|-------|
| `clarified_instead_of_answering` | **7** | Dominant; network_1 alone 4/5 |
| `wrong_table` | 1 | Mis-labeled; actually tie/`LIMIT 1` vs all ties |
| `aggregation_or_grouping` | 1 | Extra count column; same top year |
| `wrong_filter_or_value` | 1 | ASC vs DESC + extra count |
| `other` | 1 | Extra `Year_of_Work` column; same name order |
| `scorer_only` (pass values) | 3 | Alias-only; not real fails |

Schema linking is **not** the bottleneck.

## Decision table placement

**Medium band (50–75%)** on values-only — policy and conventions, not retrieval.

Variance of **+8 pp** on re-run is within sampling noise but both flips were clarification→answer, so clarification is also unstable.

### Recommended order (expected value / cost)

1. **Dial down clarification for grounded questions**  
   Use `GROUNDED_CLARIFICATION_ENABLED` (or tighten the resolver).  
   7/25 asked instead of answering despite perfect table recall and a single gold SQL.  
   Expected lift: several points immediately (network_1 was 1/5).  
   Cost: $0. Latency: slight decrease.

2. **Retrieved few-shot examples from Spider train** (not dev) via golden records  
   Helps join conventions, projection (“only asked columns”), ASC/DESC frequency sorts, tie/`LIMIT 1`.  
   Expected: largest remaining semantic gain. Low extra $ if embeddings already run.

3. **Prompt rules for Spider / eval conventions**  
   - Project only columns the question asks for.  
   - For “most common / max”, prefer `ORDER BY … LIMIT 1` unless the question says “all ties”.  
   - Be consistent on “sorted by frequency” direction.

4. **Execution-guided repair** (empty / error / suspicious shape) — after clarification is fixed.

5. **Candidate voting / stronger generator** — only if still under ~70% after (1)–(3).

### Do not prioritize yet

- Schema-linking / more tables — already 100% recall on this sample.
- Full Spider 1034 — wait until clarification + few-shot move the needle; est. ~$1.9 / ~4.5 h at current speed.

### If / when score is High (>75%)

Latency is the cost: `context_retriever` dominates (~173 s / 25 q, 3 LLM calls). Options: skip LLM table select when schema &lt; ~15 tables; parallelize expansion + golden search; skip validator when EXPLAIN + guards clean; optional formatter for eval. Target &lt;8 s/q, then re-run this same 25.

## Argusable gold vs gen

| ID | Note |
|----|------|
| `concert_singer:f22528648d5c` | Same top year; gen also returns count. |
| `orchestra:c1d9e8230efa` | Same name order; gen also returns years. |
| `orchestra:ab73cb450540` | Same formats; ASC vs DESC + extra count. |
| `course_teach:b45786ed0af6` | All hometowns tied at 1; gold `LIMIT 1` is arbitrary. |

Clarification fails are unambiguous product issues for accuracy eval.
