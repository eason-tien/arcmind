---
description: Save important information to Antigravity's persistent memory for recall in future conversations.
---

# Save to Memory

Use this workflow whenever you encounter important information that should persist across conversations.

// turbo-all

## When to Save

Automatically trigger at:
- End of a significant task (audit, implementation, debug)
- When user states a preference or correction
- When a key decision or fact is established
- When project context changes

## Steps

1. **Determine the category** for each memory entry:
   - `preference` — User preferences (language, style, tools)
   - `fact` — Technical facts (architecture, APIs, configs)
   - `decision` — Design decisions made
   - `project` — Project context (paths, structure, status)
   - `observation` — Temporary observations

2. **Determine importance** (0.0 to 1.0):
   - `0.9-1.0` — Critical (user preferences, breaking changes)
   - `0.7-0.8` — Important (architecture decisions, key facts)
   - `0.5-0.6` — Useful (observations, context)
   - `0.3-0.4` — Nice-to-know (minor details)

3. **Format as JSONL** and append to the appropriate file:

   For long-term (permanent) memories:
   ```
   echo '{"ts":"<ISO-8601>","cat":"<category>","content":"<content>","importance":<0.0-1.0>,"tags":["<tag1>","<tag2>"]}' >> /Users/eason/Code/arcmind/.agents/memory/long_term.jsonl
   ```

   For short-term (7-day) memories:
   ```
   echo '{"ts":"<ISO-8601>","cat":"<category>","content":"<content>","importance":<0.0-1.0>,"tags":["<tag1>"]}' >> /Users/eason/Code/arcmind/.agents/memory/short_term/<YYYY-MM-DD>.jsonl
   ```

4. **Update the index** at `/Users/eason/Code/arcmind/.agents/memory/index.json`:
   - Read current index
   - Add new tags to the `tags` dict (tag → count)
   - Add category to `categories` dict (cat → count)
   - Increment `total_entries`
   - Update `last_updated` timestamp
   - Write back

5. **Confirm** what was saved (brief summary, no need to repeat full content).

## Examples

### Save a user preference
```bash
echo '{"ts":"2026-03-08T08:15:00","cat":"preference","content":"用戶偏好繁體中文回覆，代碼註釋也用中文","importance":0.9,"tags":["user","language","chinese"]}' >> /Users/eason/Code/arcmind/.agents/memory/long_term.jsonl
```

### Save a project fact
```bash
echo '{"ts":"2026-03-08T08:15:00","cat":"fact","content":"ArcMind memory_store 已從 ChromaDB 遷移至 SQLite+Vector，不再有 _collections 屬性","importance":0.8,"tags":["arcmind","memory","sqlite"]}' >> /Users/eason/Code/arcmind/.agents/memory/long_term.jsonl
```
