# Task Cleaner

A local Codex plugin for macOS. It removes tracked temporary task files after completed work. Python 3.9 or later and `lsof` are required. No Python packages, network service, API key, or scheduled job are needed.

## Install

Use a Codex CLI version that supports `codex plugin`. Run these commands from any directory. Codex downloads the released plugin for you.

```sh
codex plugin marketplace add senorMk/codex-task-cleaner --ref v0.1.1
codex plugin add task-cleaner@task-cleaner-local
```

To update an existing installation, first run `codex plugin marketplace remove task-cleaner-local`, then run the install commands above.

Start a new Codex chat. Open `/hooks` and review and trust the two Task Cleaner hooks. Codex requires this trust step before local plugin hooks can run. Do not bypass hook trust. Installation alone does not activate the hooks.

For a first check, ask Codex to create a disposable file in the supplied task directory, complete the work, and mark the directory ready. After the turn, use the helper's `list` command to confirm a `removed` record.

### Install from a release ZIP

Download `task-cleaner-v0.1.1.zip` and `SHA256SUMS` from the [v0.1.1 release](https://github.com/senorMk/codex-task-cleaner/releases/tag/v0.1.1). In the download directory, check and extract the package:

```sh
shasum -a 256 -c SHA256SUMS
unzip task-cleaner-v0.1.1.zip
codex plugin marketplace add ./task-cleaner-v0.1.1
codex plugin add task-cleaner@task-cleaner-local
```

Keep the extracted directory in a permanent location. Then start a new chat and trust the hooks as described above.

### Install from a source checkout

For development, run these commands from the repository root:

```sh
codex plugin marketplace add .
codex plugin add task-cleaner@task-cleaner-local
```

All three methods use the `task-cleaner-local` marketplace. Choose one method. To change methods, first run `codex plugin marketplace remove task-cleaner-local`, then add the new source.

## Operation

1. `UserPromptSubmit` creates a private directory for the session and turn.
2. The hook tells Codex where to put disposable files and how to set `TMPDIR`, `TMP`, and `TEMP` for shell commands.
3. After the work is complete, Codex saves deliverables outside the temporary directory, waits for processes, and marks the directory `ready`.
4. `Stop` checks ready directories from that session and removes their contents.

Each directory is under `/private/tmp/codex-task-cleaner-UID/` on macOS. On macOS, `/tmp` points to `/private/tmp`. Directory names are hashes of the session and turn identifiers. Records contain no prompts or file contents. Small records remain after cleanup for inspection. There is no automatic record expiry in this version.

The hook shows a short summary after cleanup:

```text
Task Cleaner: Removed 3 task directories and 2 files (2.1 KiB).
```

For an empty task directory, the message shows zero files and zero bytes:

```text
Task Cleaner: Removed 1 task directory and 0 files (0 B).
```

If cleanup cannot finish, the message gives the reason. Repeated reasons appear once. Command-line output stays in JSON format.

If a task record is missing or invalid, Task Cleaner keeps that task's files and continues to clean other ready tasks. It reports a new or changed record problem once. Run `list` to see each damaged record and its task directory. The list includes damaged records from all sessions. Inspect the directory before you remove any files.

## Inspect and control cleanup

Use the installed helper path supplied by the hook. In a source checkout:

```sh
python3 plugins/task-cleaner/scripts/cleaner.py list
python3 plugins/task-cleaner/scripts/cleaner.py ready TASK_ID
python3 plugins/task-cleaner/scripts/cleaner.py hold TASK_ID
python3 plugins/task-cleaner/scripts/cleaner.py clean TASK_ID
python3 plugins/task-cleaner/scripts/cleaner.py clean TASK_ID --apply
```

`clean` without `--apply` is a preview. Removal requires a ready record. `hold` cancels readiness. Files needed by the user must be moved to a permanent location before readiness. Automatic removal is permanent; this plugin does not archive disposable files.

## Limits

- Codex must use the supplied directory and mark it ready. Hooks cannot change the parent process environment or redirect arbitrary file writes. Existing files elsewhere in `/tmp` and Codex's own internal temporary files are outside this plugin's scope.
- A turn can end with a question. Unfinished work stays active until Codex marks it ready. An interruption or crash also leaves files for later inspection.
- `lsof` must complete without warnings. Open files, replaced directories, hard links, mounted filesystems, and special files prevent removal.
- Internal symbolic links are removed without following their targets.
- An open-file check is a snapshot, not a process lock. Stop all writers before marking ready, including child agents. A process that starts later can race cleanup. This tool is for trusted local tasks, not hostile programs running under the same user account.
- If a hook times out, some files can remain. Inspect the directory and retry. The plugin does not assume that file age means a task is complete.
- Cleanup runs at `Stop`, before other hooks' continuation decisions are known. Mark files ready only when no later continuation will need them.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests cover session separation, retained tasks, preview, repeated events, symbolic links, hard links, replaced directories, invalid identifiers, open-file check failures, and real file removal.

## Design references

This is a fresh implementation. No source code was copied from these projects:

- [CleanMyCodex](https://github.com/SnoopyKim/CleanMyCodex): selected cleanup and protection for user outputs.
- [codex-clean](https://github.com/Merlin-Arthur05/codex-clean): a small Python helper and cleanup preview.
- [codex-cleaner](https://github.com/jedliuai/codex-cleaner): limited cleanup scope and protection for working files.

The hook contract follows [OpenAI Hooks documentation](https://learn.chatgpt.com/docs/hooks). The package follows [OpenAI plugin documentation](https://developers.openai.com/plugins/build/plugins).
