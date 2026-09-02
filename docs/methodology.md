# Reading Artificial Analysis numbers correctly

The leaderboard scraper pulls Artificial Analysis (AA) data. Two of its columns
are routinely misread, and one whole class of column does not transfer to your
environment at all. This page is about not fooling yourself.

## The Intelligence Index

A weighted composite (v4.1.1 at time of writing): Agents 34%, Coding 24%,
Scientific Reasoning 24%, General 18%. It is primarily text-and-English. Image,
speech and multilingual ability are benchmarked separately and are **not** in
this number.

## AA-Omniscience: the trap

Two columns come from it — `AA-Omniscience Accuracy` and
`AA-Omniscience Non-Hallucination Rate (1 - Hallucination Rate)` — plus the
composite `Omniscience Index`. The benchmark is 6,000 obscure-fact questions,
**1 repeat**, **no tool use**, contributing 12% of the Intelligence Index
(accuracy 8%, non-hallucination 4%).

The formulas, recovered from the published columns and validated across 18
models to within 1.5 points:

```
HallucinationRate = wrong / (wrong + abstained)
OmniscienceIndex  = correct% - confidently_wrong%
```

Read those carefully, because they mean something counter-intuitive:

- The hallucination rate is **conditional on not knowing**. It answers "when you
  did not know, how often did you invent an answer instead of abstaining?"
- The index gives **no credit and no penalty for abstaining**. Saying "I don't
  know" is free.

### The misreading to avoid

**A high non-hallucination rate does not mean the model knows more. It usually
means it abstains more.**

A model can post an excellent non-hallucination rate while answering correctly
only half as often as a model with a "worse" rate. Decompose before concluding:

```
wrong    = HallucinationRate x (100 - accuracy)
abstain  = (100 - accuracy) - wrong
```

If you want "rarely confidently wrong", look at `confidently_wrong%`. If you
want "actually knows things", look at accuracy. If you want both, look at the
Omniscience Index — and note it can go negative, which means a model is
confidently wrong more often than it is right.

### It is measured with no tools

Every agent you configure has tools. This benchmark does not. Treat it as a
proxy for "how does this model behave when asked something it cannot look up" —
relevant for advisory reasoning from memory, much less relevant for anything
that greps or fetches first.

## Throughput columns do not transfer

`Median Tokens/s` and the latency percentiles are measured against the endpoint
**AA chose**. Your serving stack, region, quantization, batching and gateway are
different, and the gap is not small. Measured on one real deployment:

| Model | AA published | Measured locally | Ratio |
|---|---|---|---|
| A GLM-5.3-Flash deployment | 43 tok/s | 255.4 tok/s (spread 16%, n=3) | **5.9x** |
| A Claude Opus 5 (xhigh) deployment | 51 tok/s | 157.3 tok/s (spread 18%, n=2) | **3.1x** |

Both were *faster* than published, by multiples. **Do not make a latency or
throughput decision from the leaderboard.** Measure your own path:

```bash
scripts/bench_throughput.sh <provider>/<model>[:variant]
```

### Why measuring this is harder than it looks

Two naive approaches both fail:

1. **Trusting harness timestamps.** Large prompts are prefix-cached; a cached
   prefill makes generation look impossibly fast and inflates the rate several-fold.
2. **Differential timing with too few samples.** Subtracting a short run from a
   long run does cancel startup — but only if the decode delta exceeds the
   startup jitter. At small token deltas and n=2, observed within-model spread
   was 1.7x-4.6x: pure noise.

`bench_throughput.sh` therefore uses a large token delta, repeats, and
**refuses to print a number when the spread exceeds a threshold** rather than
reporting a confident-looking artefact.

## Price columns

Input/output price per 1M tokens is usually reliable, but `Cost per Task` is
AA's own task mix — a model that emits more reasoning tokens costs more per task
at the same per-token price. When comparing, look at both: per-token price for
your own volume, cost-per-task as a rough reasoning-verbosity signal.
