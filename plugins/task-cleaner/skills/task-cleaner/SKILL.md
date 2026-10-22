---
name: task-cleaner
description: Use tracked temporary directories for Codex tasks. Inspect, retain, or remove temporary files created through the Task Cleaner plugin.
---

Use the directory and helper command supplied by the UserPromptSubmit hook.
Store disposable task files there. Set TMPDIR, TMP, and TEMP to that directory
for commands that create temporary files. Explicit paths must also stay there.
The hook cannot change the environment of the parent Codex process.

Before the final response for completed work:
1. Move all deliverables, useful logs, and files linked in the response to a
   permanent project or user location. Verify that those files are available.
2. Wait for child processes and agents that use the temporary directory.
3. Run the supplied `ready TASK_ID` command. The Stop hook removes the directory.

Do not mark a directory ready if work will continue, if you need user input,
or if a process can use it later. Use `hold TASK_ID` to cancel readiness.
Use `list` to find retained directories, including directories from earlier
turns. A turn is not necessarily a complete task. Mark earlier directories
ready only after their work is complete. The Stop hook checks ready directories
from the current session only.

For manual cleanup, run `clean TASK_ID` to preview, then `clean TASK_ID --apply`
only for a directory approved for removal. The helper checks readiness and
open files in both modes. It does not import or remove arbitrary paths.
Do not clear /tmp, Codex caches, or other applications' files with this skill.
