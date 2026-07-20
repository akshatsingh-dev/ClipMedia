# Pushing to GitHub — two steps, ~60 seconds

Everything is pre-wired. The remote is already set to
`git@github.com:akshatsingh-dev/ClipMedia.git` and an SSH key is generated.

I could not complete this myself: GitHub auth needs either your interactive
login or a token, and I won't handle a token. A subagent can't do it either —
same constraints.

## Step 1 — add the SSH key (30s)

Open https://github.com/settings/ssh/new and paste:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJXcn/rPSrP+FW3mS+sRFuFqDEKFKjBorIJ+hxBvYNUc akshatsingh-dev@clipmedia
```

Title it anything. The private key stays in `~/.ssh/id_ed25519_github` on this
machine and was never transmitted.

## Step 2 — create the repo (30s)

Open https://github.com/new
- Name: `ClipMedia`
- **Private** — this repo contains your full strategy doc and market research
- Do NOT initialise with a README (there's already history)

## Step 3 — push

```bash
cd /Users/akshatsingh/Desktop/Startup/ClipMedia
./push.sh
```

Or manually: `git push -u origin main`

## Verify it worked

```bash
ssh -T git@github.com     # should say "Hi akshatsingh-dev!"
git log --oneline | head  # the commits that should appear on GitHub
```
