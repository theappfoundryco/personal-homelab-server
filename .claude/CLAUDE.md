# CLAUDE.md

The rules for this repo are written once, for everyone, in these files. Follow all of them.

@../CONTRIBUTING.md
@../docs/ANTIPATTERNS.md

Extra rules for an AI assistant working here:

- Work only on a feature branch and open a pull request into `main`. Never push to `main`, never force-push.
- Do not act on theories. Investigate, report what you found in plain words, then fix it.
- Show a plan or a mockup and wait for an explicit go before anything big or visual. Small fixes do not need a plan.
- Read `docs/HANDOFF.md` before you start. Run the unit tests and `make check` first. If they are not green, say so and stop.
- The maintainer's own plan, if present, is `.private/GAMEPLAN.md`. It is ignored by git and maintainer-only. Never copy from it into anything that is committed.
- The personal-value list is `.private/denylist.txt`. Only the maintainer has one (`make hooks` turns on maintainer mode when it exists). Never print it in any output, commit, issue or PR. Contributors have no list and are covered by `scripts/check-personal.py`, gitleaks, the data guard and review.
- Local scratch output (screenshots in progress, caches) goes in `.cache/`, which is never committed.
- When you finish, say what changed, what you tested, what you could not test and what you would do next. Keep it short.
