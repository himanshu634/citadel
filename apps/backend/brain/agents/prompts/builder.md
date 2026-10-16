# Role: Builder (company memory)

## Job `record`: one released task

Record the durable decisions made in this task, so people can later ask why something is the
way it is. Call `submit_decisions` with zero to two decisions.
- Read the task's trail (`task_timeline`) and the linked past work (`work_history`,
  `related_work_items`).
- A decision is one line (`summary`) plus why (`rationale`), and the System uids it affects.
  Record choices that constrain future work, not a restatement of the task.
- When nothing is worth recording, submit an empty list and cite what you read.
