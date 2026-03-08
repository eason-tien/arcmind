---
description: Resumes a paused or in-progress long-running harness task from its last checkpoint.
---

# Resume a Harness Task

// turbo-all

## Steps

1. List all active harness run files:

```
ls -la /Users/eason/Code/arcmind/.agents/harness/active/*.json 2>/dev/null
```

2. If no files found, tell the user "沒有進行中的任務" and stop.

3. For each `.json` file found, read it with `view_file` to get the task summary.

4. If there is **only one** active run, automatically resume it. If there are **multiple**, show the user a numbered list with title, status, and progress (e.g. "2/5 steps done"), then ask which to resume.

5. Once a run is selected, read the full JSON file and identify the `current_step` index.

6. Read the `context` field from the JSON — this contains accumulated state from previous steps (notes, files modified, intermediate results). Use this as working context.

7. Execute the step at `current_step`:
   - The step's `command` field describes what to do
   - Use all available tools (file editing, terminal, browser, etc.) to complete it
   - If the step has a `skill_hint`, prefer that approach

8. After completing the step, update the JSON file:
   - Set the step's `status` to `"completed"`
   - Set the step's `output` to a brief summary of what was done
   - Set the step's `completed_at` to the current ISO timestamp
   - Update `context` with any new state (files changed, important findings)
   - Increment `current_step` by 1
   - Update `updated_at`

9. If there are more steps remaining, proceed to the next step (go to step 7).

10. When all steps are completed:
    - Set the run's `status` to `"completed"`
    - Move the file from `active/` to `completed/`:
    ```
    mv /Users/eason/Code/arcmind/.agents/harness/active/{run_id}.json /Users/eason/Code/arcmind/.agents/harness/completed/{run_id}.json
    ```
    - Notify the user that the task is complete with a summary of all steps.

11. If a step **fails**, update the JSON:
    - Set the step's `status` to `"failed"`
    - Set the step's `error` field with the error message
    - Set the run's `status` to `"paused"`
    - Notify the user of the failure and suggest `/resume` to retry after fixing.
