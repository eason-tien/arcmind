---
description: Creates a new long-running harness task with multiple steps and begins execution.
---

# Create a Harness Task

When the user asks for a complex, multi-step task that may span multiple conversations, use this workflow to create a persistent, resumable execution plan.

## Steps

1. **Analyze the user's request** and break it down into discrete, sequential steps. Each step should be:
   - Self-contained enough to execute independently
   - Small enough to complete in one tool-loop cycle
   - Clearly described so a future conversation can understand what to do

2. **Generate a run ID**: use a short, descriptive kebab-case name (e.g. `refactor-auth`, `research-llm-agents`, `migrate-db-v2`).

3. **Create the run file** at `/Users/eason/Code/arcmind/.agents/harness/active/{run_id}.json` with this structure:

```json
{
  "id": "{run_id}",
  "title": "任務標題",
  "created_at": "ISO timestamp",
  "updated_at": "ISO timestamp",
  "status": "in_progress",
  "current_step": 0,
  "context": {},
  "steps": [
    {
      "name": "步驟名稱",
      "command": "詳細的執行指令，包含足夠上下文讓未來的對話能理解",
      "status": "pending",
      "output": null,
      "error": null,
      "started_at": null,
      "completed_at": null
    }
  ]
}
```

4. **Notify the user** with the task plan summary:
   - Run ID
   - Total steps
   - Step names overview

5. **Begin executing Step 0**. Follow the same step execution logic as the `/resume` workflow:
   - Execute the step's command
   - Update the JSON with results
   - Proceed to next step
   - Continue until done or conversation ends

6. **If the conversation is ending** before all steps complete:
   - Ensure the JSON is up-to-date with current progress
   - Tell the user they can say `/resume` to continue in the next conversation
