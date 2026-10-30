# Evaluation report — default strategy

*Dataset:* `platform-v3-extended` · *cases:* 14 · *run:* 2026-10-30T07:50:49Z · *duration:* 0.3s

*Embedder:* `hash:v1:1024` · *LLM:* `none` · *vector store:* `local`

## Headline metrics

| Metric | Value | Meaning |
|---|---|---|
| Recall@5 | 100.0% | share of gold passages found in the top 5 |
| Precision@5 | 20.0% | relevant results in the top 5 (÷5) |
| MRR | 0.833 | mean reciprocal rank of the first relevant result |
| Faithfulness* | 53.1% | lexical proxy (not RAGAS) |
| Answer relevancy* | 19.7% | embedding proxy (not RAGAS) |
| Latency p50 / p95 | 17 / 31 ms | end-to-end per question |
| Tokens / query | 0 | provider-reported |
| Est. cost / query | $0.00000 | from MKA_PRICE_TABLE |

## Retrieval

| K | Recall@K | Precision@K | nDCG@K |
|---|---|---|---|
| 1 | 66.7% | 66.7% | 0.667 |
| 3 | 100.0% | 33.3% | 0.877 |
| 5 | 100.0% | 20.0% | 0.877 |

MRR: **0.833** over 3 cases with gold passages.

## Answers

| Metric | Value |
|---|---|
| route_accuracy | 100.0% |
| keyword_accuracy | 100.0% |
| exact_count_accuracy | 100.0% |
| data_accuracy | 100.0% |
| abstention_accuracy | 100.0% |
| abstained_or_flagged_low_confidence | 100.0% |
| answer_rate_on_answerable | 100.0% |
| faithfulness_lexical (proxy) | 53.1% |
| answer_relevancy_embedding (proxy) | 19.7% |
| faithfulness_llm_judge | — |
| answer_relevancy_llm_judge | — |
| false_answer_rate_on_unanswerable | 0.0% |
| citation_accuracy | 100.0% |
| citation_gold_precision | 83.3% |
| required_sources_cited | 100.0% |
| stale_or_forbidden_content_absent | 100.0% |

## By question type

| Type | Cases | Correct | Recall@5 | MRR | Route accuracy | p50 ms |
|---|---|---|---|---|---|---|
| abstain | 1 | 100.0% | — | — | — | 15.3 |
| analytics | 2 | 100.0% | — | — | 100.0% | 18.8 |
| compare | 2 | 100.0% | — | — | 100.0% | 17.4 |
| contradiction | 1 | 100.0% | — | — | 100.0% | 14.6 |
| hindi | 5 | 100.0% | 100.0% | 1.000 | 100.0% | 15.0 |
| parallel | 1 | 100.0% | — | — | 100.0% | 26.6 |
| semantic | 2 | 100.0% | 100.0% | 0.750 | 100.0% | 29.2 |

## Failures (0)

None.

## Notes

- Faithfulness/relevancy marked (proxy) are lexical/embedding heuristics, not RAGAS; the LLM-judge values exist only when an LLM is configured.
- Token counts are provider-reported when available, otherwise estimated at ~4 characters per token; cost uses MKA_PRICE_TABLE.
- citation_accuracy = share of returned citations whose page/row exists and whose excerpt occurs there (checked by the Verification Agent); agent execution success = no internal error or timeout in any agent node.
