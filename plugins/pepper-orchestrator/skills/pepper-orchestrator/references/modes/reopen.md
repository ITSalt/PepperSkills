# Mode: reopen

Make a closed program active again, when its own goal turned out not to be reached (not for a new
goal: that is a new program). Argument: the reason.

```bash
python3 SKILL_DIR/scripts/orch.py reopen "<reason>"
```

It sets `state: active`, notes the reopening under the closed banner of `status.md` and writes
the journal line. An archived workspace (`features/_archive/<program>`) is reopened in place; the
command prints the `git mv` to move it back if the owner wants. Then continue with `resume`.
