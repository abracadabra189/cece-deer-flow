# CeCeMate local manual retrieval

An independently packaged read-only knowledge provider named `cecemate-manual`.
It loads and validates the bundled `data/entries.json`, `manifest.json` and
`aliases.json` once during synchronous extension installation, then builds an
in-memory index. Async search performs no file IO, network requests, model calls,
embedding calls or writes. Restart Gateway to load a new packaged corpus.

Register the package entrypoint `deerflow_extension_cecemate_manual:install` in
operator-controlled `plugins:`. Connect the existing tool as follows (merge into
your deployment configuration; installing this package does not edit it):

```yaml
plugins:
  - use: deerflow_extension_cecemate_manual:install
    enabled: true
    required: true
knowledge_base:
  enabled: true
tools:
  - name: knowledge_search
    group: knowledge
    use: deerflow.knowledge.tools:knowledge_search_tool
    provider: cecemate-manual
tool_groups:
  - name: knowledge
```

The manual is shared with every user allowed to invoke this provider. It advertises
only `search` and `sources`; the host enforces disabled scope and rejects selected
datasets/documents. There is no catalog, ACL mapping, management API or import tool.
Do not put private per-user evidence in this shared corpus.

Retrieval uses dependency-free Chinese overlapping bigrams and whole Latin/digit
tokens after NFKC/case normalization, BM25 with title/alias/scenario weighting,
and one-hop bidirectional expansion from the packaged alias dictionary. There are
no special cases for individual questions. It ranks across modules, returning at
most six hits. Blank, punctuation-only and unmatched queries return no evidence;
queries over the configured character limit fail. Lexical retrieval cannot infer
unlisted synonyms. Generic question words do not establish topic coverage;
queries with fewer than half of their substantive bigrams in the corpus abstain.
This lexical coverage gate is not a probability of correctness. Retired entries require their actual retired title (ignoring
the retirement suffix), so a generic mention of 公告 never unlocks them.

Optional strict integer plugin settings: `max_hits` (default 6, range 1–6),
`max_query_chars` (512, 1–2048), `max_excerpt_chars` (800, 1–800), and
`max_total_chars` (4800, 1–4800). Unknown keys and booleans fail startup.
The total budget counts evidence characters; citation titles are added by the host.
These bounds fit the unchanged host defaults (800 per chunk, 8000 total), including
citation overhead for the shipped chapters. Long entries select exact sentence fragments plus all
identified caveat fragments, marked as partial in citation titles; an entry is
omitted if its evidence and caveats cannot fit together. Every individual fragment
is bounded to 800 characters or the smaller configured limit. No ellipsis or generated
text is inserted into source evidence. Source contradictions are preserved.
Chapter, manual version and date appear in citation titles; URLs/pages are absent
because the corpus does not establish them. Source SHA-256 identifies the original
manual; when present, entries SHA-256 is checked against the packaged JSON bytes.
Optional structured entry fields are accepted without changing original content.

The wheel includes Python code, all three corpus JSON files and bilingual
`deerflow-extension.json`. From the repository root, verify without installing:

```powershell
uv run --no-sync --project backend pytest D:/project/pythonProject/deer-flow/examples/deerflow-extension-cecemate-manual/tests/test_retrieval.py D:/project/pythonProject/deer-flow/examples/deerflow-extension-cecemate-manual/tests/test_provider.py -q
uv run --no-sync --project backend python scripts/check_extension.py examples/deerflow-extension-cecemate-manual
```

The fixture suite covers ranking, aliases, cross-module retrieval, retired gating,
input validation, evidence budgets and host citation replay. Actual-corpus checks
exercise the seven product questions against the packaged manual. The separate
corpus builder and its tests audit the source conversion.
