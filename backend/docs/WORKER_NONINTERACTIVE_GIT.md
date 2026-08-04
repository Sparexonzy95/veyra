# Veyra Worker Non-Interactive Git Hotfix v0.1.1

This hotfix removes browser and terminal approval prompts from worker Git pushes.

## What changed

- Disables Git Credential Manager for the worker push child process.
- Clears configured Git credential helpers for that child process.
- Forces a short-lived `GIT_ASKPASS` helper.
- Sets `GIT_TERMINAL_PROMPT=0`.
- Sets `GCM_INTERACTIVE=Never`.
- Sets `GCM_GUI_PROMPT=0`.
- Keeps the GitHub token out of remote URLs, command arguments, logs, commits,
  Django models, and OpenCode.
- Deletes the temporary credential helper automatically after use.
- Decodes subprocess output as UTF-8 with replacement, preventing the Windows
  `cp1252` `UnicodeDecodeError` seen during OpenCode execution.

## Verification command

```powershell
python manage.py check_worker_git_auth
```

The command:

- verifies the configured GitHub account;
- proves Git can obtain the worker credential without a browser or terminal;
- does not clone, modify, commit, push, or open a pull request;
- never prints the token.

## Expected output

```text
Non-interactive Git authentication passed.
GitHub account: logicbloomlab
Browser prompts: disabled
Git Credential Manager: bypassed for worker pushes
Credential source: temporary GIT_ASKPASS helper
GitHub token stored in database: no
No repository was modified and no push was performed.
```
