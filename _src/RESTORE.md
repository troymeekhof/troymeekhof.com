# Restoring the pre-redesign site

On 2026-11-01, before the design pass (Stageshow craft rules), the /banned copy rewrites and the SEO cleanup, the whole live site was frozen on the branch:

    backup/pre-redesign-2026-11-01   (commit 259d347)

That branch is never deployed (deploys only run from `main`) and must never be deleted or edited.

## Restore the whole site
Troy has to ask for this. Then, from an up-to-date clone of `main`:

    git checkout main && git pull
    git checkout backup/pre-redesign-2026-11-01 -- .
    git rm -r --cached -q . >/dev/null && git add -A   # stage exactly the backup's file set
    git commit -m "Restore pre-redesign site from backup/pre-redesign-2026-11-01 [allow-revert] [allow-delete] [allow-shrink]"
    git push

Files added after the backup (new pages, new images) are removed by this; the commit tokens let the guard accept that, since Troy asked for it.

## Restore one page or one file

    git checkout backup/pre-redesign-2026-11-01 -- path/to/index.html
    git commit -m "Restore path/to/index.html from pre-redesign backup [allow-revert]"

## Compare old and new

    git diff backup/pre-redesign-2026-11-01 main -- assets/style.css
