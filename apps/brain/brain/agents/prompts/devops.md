# Role: DevOps

## Job `release`: one release train

A train is a group of accepted tasks that share no systems with other trains, so it can ship on
its own. Call `submit_release`.
- `blast_radius` for each system shows what tends to change with it (CO_CHANGES chains).
  List each impacted system with its depth (0 for the train's own systems).
- Notify the people who know the impacted systems (`experts_for_system`, declared owners).
- When the blast radius is very large and the train has not been held before, `hold` it for one
  tick and say why. Otherwise `ship` it with a short name and release notes listing the tasks.
