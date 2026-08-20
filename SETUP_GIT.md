# Move to your dev folder, then set up Git (run natively — Claude Code / Terminal)

A stray `.git/` was created by a sandboxed tool that couldn't finalize it. Move the project,
delete that `.git`, and init fresh.

```bash
# 1) Move into your dev folder
mv "/Users/Kay/Claude/Projects/Tanaghom (Content Dept) Workflow/tanaghom" /Users/Kay/Dev/

# 2) Init a clean repo
cd /Users/Kay/Dev/tanaghom
rm -rf .git
git init -b main
git add -A
git commit -m "Initial commit: Tanaghom content dept — blueprint, methodology, schema, Foundation stack"

# 3) Create the GitHub repo and push (GitHub CLI)
gh repo create tanaghom --private --source=. --remote=origin --push
# — or, if creating the repo manually on github.com:
# git remote add origin git@github.com:<your-username>/tanaghom.git
# git push -u origin main
```

Then on Windows: `git clone` the repo and follow `docs/03_Foundation_Local_Setup.md` for M1.
