# Linear fixtures

`synthetic-co/` is a Linear cache in the shape `brain.adapters.linear.fetch` writes
(`meta.json`, `teams.json`, `issues/`). It is hand-written in API shape, not recorded from a real
workspace. Task 10 re-records it from a real workspace; keep the shape and the cases below.

`issues/state.json` lists two completed runs. The second run holds a newer version of `i-7`,
which moved from team IDN to team PAY and got a new identifier. Like a real run, it also holds
every issue that is still open (`i-1`, `i-2`, `i-3`, `i-6`, unchanged): the issues query always
returns open issues, and the transform marks an open issue missing from the newest run as removed
from Linear. Only the closed `i-4` and `i-5` are absent from it.

Cases covered: an assigned ticket (`IDN-1`) and unassigned ones; BLOCKS through `relations` only
(`i-6` -> `i-1`), through `inverseRelations` only (`i-5` -> `i-3`) and on both sides (`i-1` ->
`i-2`); a blocker that is not in the cache (`i-9`); `related` and `duplicate` relations; an
attachment URL; a comment whose user is null; state types `triage` and `weird_new_type`;
priority 0; a due date; a ticket with no creator; a member with a blank display name.
