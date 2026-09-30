# Liquid d1 decision evaluation — 2026-09-30

A reproducible, original Japanese/English synthetic decision benchmark of Liquid's `d1:free` API. Created for 海外テックの「これマジ?」. This is an independent experiment, not an official Liquid benchmark.

**552 independent items, 120 paired variants, 60 identical-input controls.** All 853 API attempts, including transport failures and basic/static-Tetris tests, are retained. Independent items are not the same as request counts.

| Primary task (hard, n=120 each) | Correct | Accuracy | Holm-adjusted one-sided p vs 25% |
|---|---:|---:|---:|
| Rules with exceptions | 66 | 55.0% | 4.77e-12 |
| State tracking with moves/cancellations | 32 | 26.7% | 0.370 |
| Constrained assignment selection | 68 | 56.7% | 4.88e-13 |

The rule and assignment tasks exceeded uniform chance on this generated distribution. The temporal result did not establish above-chance performance. This is not a comparison with another model, nor evidence of dependable autonomous decisions. See the report for Wilson intervals, denominators and limitations.

- [日本語の詳細レポート](RESULTS.md)
- [データセット仕様](dataset/README.md)
- [Methods and publication provenance](METHODOLOGY.md)
- [Machine-readable primary results](hard-summary.json) and [full summary](final-summary.json)
- [All attempts](runs/) and [inputs, gold answers and witnesses](dataset/private-decisions-v5/items.jsonl)
- Download [viewer.html](viewer.html) and open it locally for the searchable interactive report. GitHub's file view does not run HTML.

## Recompute without an API key

Python 3.10+; standard library only. No network requests are made by these commands.

```bash
python3 analyze.py
python3 verify.py
```

Recreate the exact evaluated dataset (the destination must not exist):

```bash
python3 generate_dataset.py \
  --seed liquid-private-decisions-20260930-a7e4169f \
  --version private-decisions-v5 \
  --output /tmp/decision-test-reproduced
```

Expected `items.jsonl` SHA-256: `ae041f64200422422f8cb1b3307c579a697ed10ca11e9b528bec4e7e1d0f6f60`.

For a new model evaluation, choose a **fresh seed**, fix the test plan before inspecting model answers, and send only each item's `payload`, never its gold answer or witness. The historical dataset name `private-decisions-v5` is preserved for reproducibility; it is now public. Novel instances do not guarantee novel task formats, and this fixed set has already been sent to Liquid.

The archived runners document the original serial transport behavior. They call a live API only when explicitly run, require `LIQUID_API_KEY`, and should not be used to infer current pricing or service limits. `analyze.py`, `verify.py`, and `generate_dataset.py` are entirely offline.

Real-time Tetris and inference speed were not evaluated. Static Tetris inputs already included code-computed candidate outcomes and line counts. Historical Jev agreement is not a correctness score.
