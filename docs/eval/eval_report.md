# Evaluation report — default strategy

*Dataset:* `synthetic-mixed-v1` · *cases:* 42 · *run:* 2026-10-30T05:42:51Z · *duration:* 0.66s

*Embedder:* `hash:v1:1024` · *LLM:* `none` · *vector store:* `local`

## Headline metrics

| Metric | Value | Meaning |
|---|---|---|
| Recall@5 | 90.9% | share of gold passages found in the top 5 |
| Precision@5 | 18.2% | relevant results in the top 5 (÷5) |
| MRR | 0.909 | mean reciprocal rank of the first relevant result |
| Faithfulness* | 88.9% | lexical proxy (not RAGAS) |
| Answer relevancy* | 26.7% | embedding proxy (not RAGAS) |
| Latency p50 / p95 | 9 / 28 ms | end-to-end per question |
| Tokens / query | 0 | provider-reported |
| Est. cost / query | $0.00000 | from MKA_PRICE_TABLE |

## Retrieval

| K | Recall@K | Precision@K | nDCG@K |
|---|---|---|---|
| 1 | 90.9% | 90.9% | 0.909 |
| 3 | 90.9% | 30.3% | 0.909 |
| 5 | 90.9% | 18.2% | 0.909 |

MRR: **0.909** over 22 cases with gold passages.

## Answers

| Metric | Value |
|---|---|
| route_accuracy | 100.0% |
| keyword_accuracy | 92.3% |
| exact_count_accuracy | 100.0% |
| data_accuracy | 100.0% |
| abstention_accuracy | 75.0% |
| abstained_or_flagged_low_confidence | 100.0% |
| answer_rate_on_answerable | 97.2% |
| faithfulness_lexical (proxy) | 88.9% |
| answer_relevancy_embedding (proxy) | 26.7% |
| faithfulness_llm_judge | — |
| answer_relevancy_llm_judge | — |
| false_answer_rate_on_unanswerable | 25.0% |

## By question type

| Type | Cases | Correct | Recall@5 | MRR | Route accuracy | p50 ms |
|---|---|---|---|---|---|---|
| abstain | 4 | 75.0% | — | — | — | 8.0 |
| data | 9 | 100.0% | — | — | 100.0% | 23.2 |
| exact | 6 | 100.0% | 100.0% | 1.000 | 100.0% | 7.4 |
| intel | 2 | 100.0% | — | — | 100.0% | 9.1 |
| semantic | 21 | 90.5% | 90.5% | 0.905 | 100.0% | 8.5 |

## Strategy comparison

| Strategy | Recall@5 | Precision@5 | MRR | nDCG@5 | p50 ms | p95 ms | $/query |
|---|---|---|---|---|---|---|---|
| semantic | 86.4% | 17.3% | 0.833 | 0.841 | 7.3 | 24.6 | 0.00000 |
| keyword (BM25) | 86.4% | 17.3% | 0.864 | 0.864 | 7.8 | 26.0 | 0.00000 |
| hybrid | 86.4% | 17.3% | 0.833 | 0.841 | 8.8 | 28.2 | 0.00000 |
| hybrid + lexical rerank | 86.4% | 17.3% | 0.864 | 0.864 | 8.1 | 26.2 | 0.00000 |
| hybrid + rerank + parent-child + corrective | 90.9% | 18.2% | 0.909 | 0.909 | 8.6 | 25.9 | 0.00000 |
| hybrid + multi-query + graph | 90.9% | 18.2% | 0.909 | 0.909 | 11.1 | 44.6 | 0.00000 |

## Failures (3)

- `h01` How much vacation time do staff get yearly? — keywords_ok, no relevant passage in top 5
- `h03` What is the cost of the Pro subscription per month? — keywords_ok, no relevant passage in top 5
- `a02` What was the weather in Pune yesterday? — abstained_ok

## Notes

- Faithfulness/relevancy marked (proxy) are lexical/embedding heuristics, not RAGAS; the LLM-judge values exist only when an LLM is configured.
- Token counts are provider-reported when available, otherwise estimated at ~4 characters per token; cost uses MKA_PRICE_TABLE.
