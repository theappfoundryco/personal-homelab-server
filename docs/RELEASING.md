# Releasing

A release is made by raising the version number. Nobody types `git tag`.

## How it works
1. Work happens on branches, each one a pull request into `main`.
2. The **title** of each pull request (or each commit, with a merge commit) is a line in the release notes:
   - `security: ...` shows as **Security**
   - `feat: ...` shows as **New**
   - `fix: ...` shows as **Fixed**
   - `docs:`, `chore:`, `test:`, `ci:`, `refactor:` and `release:` are left out.
3. When `main` has everything for the release, one small pull request raises `VERSION` in `core/version.py`.
4. Merging it is the release. The **Cut release** workflow tags that commit, writes the GitHub Release with the notes, and builds the images. Everyone on the stable channel is offered it in the dashboard, and on Telegram.

## Step by step

**Work on as many branches as you like** (from your development clone, never the install folder):

```bash
git switch main && git pull --ff-only origin main
git switch -c feat/short-name
# ...work, commit, then:
make check && python3 -W ignore -m unittest discover -s tests
git push -u origin feat/short-name      # open a pull request, title in the prefix style above
```

Merge each pull request when it is ready. Squash is fine: the pull request title becomes the line in the notes.

**When main is ready to ship**, make the release pull request:

```bash
git switch main && git pull --ff-only origin main
git switch -c release/0.3.0
python3 scripts/release.py preview      # shows the version and the notes everyone will see
```

Change `VERSION` in `core/version.py` to the new number, commit it as `release: 0.3.0`, push, and open the pull request with the same title. Merge it. Within a minute or two the release is on GitHub.

**Which number:** only fixes or security fixes, raise the last part (0.2.1 to 0.2.2). Anything new, raise the middle and reset the last (0.2.1 to 0.3.0).

## Check it
- GitHub, Releases: the new version with its notes.
- In the dashboard: Settings, Updates, **Check now**.

## When something goes wrong
- **No release appeared:** GitHub, Actions, **Cut release**: read the failed step. You can run it again from there with **Run workflow**.
- **It refused the version:** the new number must be higher than the last release.
- **A line in the notes reads badly:** edit the GitHub Release text. The dashboard reads commit sentences, so for next time write the title for the person using the homelab: `fix: stop the weather card showing yesterday`, not `fix: tz bug`.
- **A release has a bug:** never move or delete a tag people may have installed. Fix it and release the next number.
