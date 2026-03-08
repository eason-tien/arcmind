---
description: Shows the status of all harness tasks (active, paused, and recently completed).
---

# Harness Task Status

// turbo-all

## Steps

1. List active runs:

```
ls -la /Users/eason/Code/arcmind/.agents/harness/active/*.json 2>/dev/null
```

2. List recently completed runs:

```
ls -lt /Users/eason/Code/arcmind/.agents/harness/completed/*.json 2>/dev/null | head -5
```

3. For each active run file, read it and extract:
   - `title`
   - `status`
   - `current_step` / total steps
   - Time since last update

4. Present a summary table to the user:

```
| Run ID | Title | Status | Progress | Last Updated |
|--------|-------|--------|----------|--------------|
| xxx    | ...   | ...    | 2/5      | 5 min ago    |
```

5. If there are paused or failed runs, suggest the user can say `/resume` to continue them.
