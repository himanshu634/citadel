# AI usage

I used Claude Code to write the code: the Python packages, the Cypher queries, the tests, the
Svelte app and most of the docs. The design is mine. I decided the architecture and the rules
the agents follow, and I picked every screen from mockups before it was built. I reviewed and
merged every change.

## How I used it

- **Building.** I describe a part and the rules it must follow. Claude writes the code and its
  tests on a branch, and I review it before it is merged.
- **Trade-offs.** When a choice has more than one reasonable answer, I ask Claude to lay out the
  options and what each one costs. I make the call.
- **Mockups.** For each screen, Claude draws a few directions from my brief. I pick one, often
  with changes, and the screen is built from it.
- **Testing.** Claude runs the test suites and the app against a local FalkorDB, and fixes what
  fails before I review.
