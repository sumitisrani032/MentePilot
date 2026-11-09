# Evaluation

52 realistic customer questions check the whole agent flow against a real catalog. The cases are in
`backend/evals/dataset.yaml`. The latest answers to each one are in
[evaluation-results.md](evaluation-results.md).

## What is measured

| Measure | Target | Meaning |
| --- | --- | --- |
| Relevant in the top 5 | 80% | Share of the first 5 products that match the case |
| Fact violations | 0 | Products that break a limit in the case, such as a budget or a forbidden attribute |
| Invented products | 0 | Products that are not in the catalog |
| Replies containing a price | 0 | The model wrote an amount of money |

A case lists `relevant_if` and optionally `forbid_if` conditions, written against the merchant's
own CSV attribute columns.

```yaml
- query: I'm going to the beach, suggest me some products
  relevant_if:
    - {types: [Sunscreen, After-Sun Care]}
    - {attributes: {Occasions and activities: [Beach]}}
```

| Part of the set | Examples |
| --- | --- |
| Occasions and situations | Beach, wedding, gym, date night |
| Weather and climate | Humid, skiing, monsoon, polluted city |
| Skin and hair concerns | Dark marks, chapped lips, split ends |
| Direct product requests | Red lipstick, nail polish |
| Budgets | "a cheap cleanser, my budget is 10" |
| Routines | "simple routine for a beginner" |
| Traps with a hard limit | "waterproof makeup for a pool party" |

## How to read the score

The score is strict and has known limits, so treat it as a way to compare runs.

- Only the first 5 picks count, although answers often show 6 to 9 across sections.
- A sensible product can score zero when the merchant's columns do not list that exact word.
- Identical runs differ, because the model is not deterministic.

## Running it

It calls OpenAI for every question. The merchant CSV is not in the repository, because it holds
cost prices.

```bash
cd backend
LLM_CALLS_ENABLED=true uv run python -m evals.run_eval \
  --csv /path/to/catalog.csv \
  --shop-domain cosmo-genie.myshopify.com \
  --report ../docs/evaluation-results.md
```

`--shop-domain` scores a store that is already indexed. Without it the catalog is imported into a
new evaluation store first, which costs more.
