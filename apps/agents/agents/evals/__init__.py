"""Offline evals for the brain agent: golden questions on a loaded company graph.

Why: `make test` proves the loop's mechanics with a scripted client; it can't say whether a real
model picks the right tools and cites the right nodes. An eval run asks Claude each question in
`cases/<slug>.yaml` against brain_<slug>, grades the answer with deterministic checks (cited uids,
tools used, answer text, step count) and writes one JSONL line per run to data/evals/<slug>/.
It calls the API, so it lives outside `make test`: `make eval SLUG=synthetic`.

    cases.py   case file schema, and gold uids resolved from the graph at run time
    graders.py pure checks: (expectation, answer, steps) -> list of Check
    run.py     runs cases (repeats, threads for follow-ups), summary, baseline compare
    report.py  Markdown tables from result files (docs/evals.md is generated with it)
"""
