# Benchmark data (Spider / BIRD)

Downloaded datasets live under `data/` (git-ignored).

## Spider

- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- Citation: Yu et al., EMNLP 2018 — *Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task*
- Source package: Hugging Face `HAL-9001/spider-databases` (`spider_data.zip`)

Download:

```bash
uv run python -m src.eval.pilot --download-only
```

## BIRD Mini-Dev

Not used by the five-question pilot. See the separate Spider/BIRD evaluation plan.
