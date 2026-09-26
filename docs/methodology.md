# Reading Artificial Analysis numbers correctly

## Coverage, identity, and local provenance

The models UI defaults to current models. Collect `?status=all`, verify Status:
All, and expand columns before concluding that an older model has no data.
`?deprecation=all` is not the models table's status control.

The join preserves configured chain order, not global score order. It separates
model identity from reasoning effort and evaluation qualifiers. `auto` cannot
be silently mapped to `max`; all available candidate rows remain in JSON when
effort is unresolved. A single unlabeled row can supply measurements, but does
not establish effort equivalence. Non-reasoning subvariants and `with fallback`
remain explicit. Do not compare different evaluation policies as equivalent.

Fast-to-base matches are proxies for every metric, including cost and throughput.
Exact Fast rows take precedence; Pro remains a separate identity. `*` marks
estimated cells and survives as metadata. An unmatched identity means the row
is absent from this input, not that AA never benchmarked it. A missing cell in
an otherwise matched row is distinct from an unresolved effort.

Store CSVs and hash-bound manifests locally only. Each collection records its
source URL, scope, collection time, headers, row count, and content hashes; an
immutable local copy retains its original manifest. Check the timestamp before
claiming freshness. Unknown benchmark revisions remain explicit; this tool does
not establish comparability across revisions. Never commit, upload, or attach
real AA exports or reports. Tests use invented measurements.

## Historical benchmark interpretation

The version-specific notes below are historical observations. Recheck AA's
current methodology before relying on these weights or formulas for a new audit.

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

The formulas below are inferred from the published columns, not published by AA.
They reproduce the published values closely on the models spot-checked, but
treat them as a reading aid rather than a specification:

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
different, and the gap is routinely a multiple in either direction — not a few
percent. **Do not make a latency or throughput decision from the leaderboard.**
Measure your own path:

```bash
scripts/bench_throughput.sh <provider>/<model>[:variant]
```

### Why measuring this is harder than it looks

Two naive approaches both fail:

1. **Trusting harness timestamps.** Large prompts are prefix-cached; a cached
   prefill makes generation look impossibly fast and inflates the rate several-fold.
2. **Differential timing with too few samples.** Subtracting a short run from a
   long run does cancel startup — but only if the decode delta exceeds the
   startup jitter. At small token deltas and low repeat counts, run-to-run
   spread can exceed the difference you are trying to measure.

`bench_throughput.sh` therefore uses a large token delta, repeats, and
**refuses to print a number when the spread exceeds a threshold** rather than
reporting a confident-looking artefact.

## Price columns

Input/output price per 1M tokens is usually reliable, but `Cost per Task` is
AA's own task mix — a model that emits more reasoning tokens costs more per task
at the same per-token price. When comparing, look at both: per-token price for
your own volume, cost-per-task as a rough reasoning-verbosity signal.
