# History rewrite test (privacy)

This branch **`cursor/privacy-history-scrub-65e9`** removes the merged AdoRime toy
app commit from **git history** by rebasing `main` so jet_radar (#11) sits directly
on mac_battery (#8), skipping PR #7 entirely.

## What this removes from git

- The merge commit and tree for PR #7 (no `src/adorime_control/`, no toy tests)
- Commit messages on this line that referenced AdoRime (commit no longer exists)

## What this does **not** remove

- GitHub PR #7 / closed PRs / issue comments (still on GitHub)
- Cursor agent transcripts and account audit logs
- Forks/clones that already fetched old `main` SHAs

## Applying to `main` (destructive)

Only the repo owner should do this:

```bash
git checkout main
git reset --hard cursor/privacy-history-scrub-65e9
git push --force-with-lease origin main
```

All collaborators must re-clone or hard-reset. GitHub may retain unreachable
objects for a while; contact GitHub support only if you need enterprise-level
data removal policies.

## Safer alternative

Merge PR #14 (revert) instead — keeps history, removes current files.
