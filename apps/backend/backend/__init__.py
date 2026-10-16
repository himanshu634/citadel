"""Company Brain backend: the HTTP API the frontend talks to, and the operator commands around it.

Why: the `brain` package builds and queries the company graph, and `agents` answers from it.
This package puts both behind one server (`backend.api:app`): the company registry, build jobs,
onboarding and config diffs. It depends on `brain` and `agents`, and neither depends on it.
"""
