# Local modifications to the vendored scraper

Upstream: <https://github.com/deyil/artificial-analysis-leaderboards-scraper>
Pinned commit: `99167bae89b203e427c48f04edcf7366eae04ef5`
License: GPL-3.0 (upstream `LICENSE` preserved unmodified)

Local changes needed for usable model-table output. All collected data and
provenance stay local; this repository distributes only code and synthetic tests.

## 1. `config.yaml` — `target_url` returned 404

The upstream default pointed at a leaderboard route that no longer exists; the
site restructured. Every run failed with `No table found in HTML content` after
two Playwright attempts.

```diff
-target_url: "https://artificialanalysis.ai/leaderboards/providers/prompt-options/single/medium_coding?deprecation=all"
+target_url: "https://artificialanalysis.ai/leaderboards/models?status=all"
```

## 2. `src/components/parser.py` — the first column came back entirely empty

`extract_provider_name()` only looked for an `<img>` logo in the row's first
cell. On the models leaderboard the first cell contains the model name as an
anchor / text node, not a logo, so the function returned `""` for every row.

Observed: `Model` column non-null **0 of 286** rows before, **286 of 286** after.

```diff
-    # If no img or no usable attributes, return empty string
-    return ""
+    # No usable image metadata: fall back to the cell's own text.
+    # The models leaderboard renders the entity name as an anchor/text node in
+    # the first cell rather than a provider logo, so an img-only lookup returns
+    # "" for every row and yields an entirely empty first column.
+    anchor = cell.find("a")
+    text = anchor.get_text(" ", strip=True) if anchor else cell.get_text(" ", strip=True)
+    return " ".join(text.split())
```

This is additive: rows that *do* carry a logo still take the `<img>` path first,
so provider leaderboards are unaffected.

Upstream's own `tests/test_parser.py::test_extract_provider_name_no_img` pinned
the old `""` return, so it was updated to encode the new intent, and two
boundary cases were added alongside it: a genuinely empty cell still returns
`""`, and anchor text is whitespace-normalised. The vendored suite passes.

## 3. `config.yaml` — locale formatting corrupted numbers for analysis

Upstream defaults to localizing decimals, which rewrote `85.5` as `85,5` and
broke numeric parsing and sorting downstream. Timestamped filenames were also
disabled so the output path is stable for scripting.

```diff
-output_add_timestamp: true
+output_add_timestamp: false
-output_localize_numbers: true
+output_localize_numbers: false
```

## 4. Model scope and expanded columns

The models table defaults to current models, hiding older models with valid
measurements. Normalize its URL to `status=all`, open its Status dialog, uncheck
Current, verify Status: All, and expand the metric columns. The old
`deprecation=all` query did not control this table. Use locator/state waits rather
than fixed delays. Other leaderboard routes retain their existing behavior.

## 5. Failure propagation and atomic local output

The entry point returns nonzero on fetch, parse, validation, or write failure,
so the shell wrapper cannot accept an old CSV as a fresh success. Validate model
names, row widths, required headers, and duplicate columns before replacing the
latest CSV. Write through a flushed temporary file followed by atomic replace.

## 6. Local-only reproducibility

`snapshot.py` records scope, source URL, collection time, row count, headers,
CSV and HTML hashes, and an explicitly unresolved benchmark revision when it is
not exposed. Store a content-addressed local CSV and its original manifest, plus
a latest manifest. Consumers verify the CSV hash and reject mismatched pairs.
The shell wrapper copies the matching manifest with `--out`.

Regression fixtures are synthetic. No AA HTML, metrics, CSVs, screenshots, or
generated reports are distributed with these patches.
