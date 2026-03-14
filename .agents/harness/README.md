# Antigravity Self-Harness

This directory contains the persistent state for long-running tasks managed by Antigravity (IDE Agent).

## Structure

```
harness/
├── active/            ← In-progress task run files (.json)
├── completed/         ← Archived completed runs (.json)
└── README.md          ← This file
```

## How It Works

1. **Create**: User asks for a multi-step task → Antigravity creates a `.json` run file in `active/`
2. **Execute**: Steps are executed one by one, JSON updated after each step
3. **Resume**: If conversation ends mid-task, user says `/resume` in next conversation
4. **Complete**: All steps done → file moved to `completed/`

## Run File Format

Each `.json` file contains:
- `id`, `title`, `status` — basic metadata
- `steps[]` — ordered list of steps with individual status/output
- `current_step` — index of next step to execute
- `context` — shared state across steps (notes, files modified, etc.)
