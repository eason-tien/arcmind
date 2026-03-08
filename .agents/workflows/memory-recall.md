---
description: Load Antigravity's persistent memory at the start of a new conversation for context continuity.
---

# Recall Memory

Use this workflow at the start of a new conversation to load relevant context from past sessions.

// turbo-all

## Steps

1. **Read long-term memory** — load the most recent and highest-importance entries:
   ```bash
   tail -50 /Users/eason/Code/arcmind/.agents/memory/long_term.jsonl 2>/dev/null || echo "No long-term memories yet"
   ```

2. **Read recent short-term memory** — load the last 7 days:
   ```bash
   find /Users/eason/Code/arcmind/.agents/memory/short_term/ -name "*.jsonl" -mtime -7 -exec cat {} \; 2>/dev/null || echo "No short-term memories"
   ```

3. **Read index summary** for a quick overview:
   ```bash
   cat /Users/eason/Code/arcmind/.agents/memory/index.json 2>/dev/null || echo "No index"
   ```

4. **Clean up expired short-term memories** (older than 7 days):
   ```bash
   find /Users/eason/Code/arcmind/.agents/memory/short_term/ -name "*.jsonl" -mtime +7 -delete 2>/dev/null
   ```

5. **Synthesize a context summary** from the loaded memories:
   - Group by category
   - Prioritize high-importance entries
   - Format as a concise internal briefing
   - Report the summary to yourself (do not output to user unless asked)

## Output Format

After loading, internally note the key points as:
```
[Memory Loaded]
- Preferences: ...
- Key Facts: ...
- Recent Decisions: ...
- Active Projects: ...
- Observations: ...
Total: N long-term, M short-term entries
```

## When to Use

- **Always**: At the start of any new conversation where context from past sessions is relevant
- **User trigger**: When user says `/memory-recall`
- **Auto**: After a `/resume` to supplement the harness context with background knowledge
