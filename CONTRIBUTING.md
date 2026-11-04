# Contributing

Improvements from people running their own homelab are welcome. Your data never needs to leave your machine to do it. Small, focused pull requests are the easiest to review and the fastest to merge. If you are not sure something fits, open a [discussion](https://github.com/theappfoundryco/personal-homelab-server/discussions) first. Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Where your stuff lives
- **Code**: this repository. The only thing a pull request ever contains.
- **Your data** (apps, keys, journal, stats): `~/.homelab/`, outside the repository. Git never sees it.
- **Your settings**: `stack/config.yaml` and `stack/.env`. Ignored by git. Never put your values in `config.example.yaml` or `*.env.example`.

## Set up
You need Python 3 with PyYAML, git, and Docker (the installer can set Docker up for you). The unit tests need nothing else.

```bash
git clone https://github.com/<your-username>/personal-homelab-server.git   # your fork
cd personal-homelab-server
pip install pyyaml
make hooks        # once; also: brew install gitleaks
```

## Flow
1. Fork this repository on GitHub and clone your fork (or add it as a remote to your existing install: `git remote add fork <your fork URL>`).
2. Run `make hooks` once. Every commit is then checked for env files, data, keys, emails and public IP addresses.
3. Make a branch: `git switch -c fix/short-name`. Never push to `main`.
4. Make the change, then run the checks below.
5. Push to your fork and open a pull request into `main`. CI runs the same checks, and the maintainer reviews every change.
6. After it is merged, everyone gets it with `homelab update`. Your settings and data are left alone.

## Check your work
```bash
python3 -W ignore -m unittest discover -s tests   # unit tests, about 40 seconds
make check                                        # data guard, emails and public IPs, design tokens, image pins, gitleaks
make test-e2e                                     # dashboard smoke tests on demo data (pip install playwright; playwright install chromium)
```

You do not need the maintainer's private list of personal values. Contributors are covered by `scripts/check-personal.py` (emails and public IP addresses), gitleaks, the data guard and review.

To try the installer from scratch as often as you like, use `scripts/dev-reset.sh` (see `--help`). It only removes this project's containers, data folder and files.

## Commits and pull requests
- One task per branch, kept small.
- Commit messages and PR titles start with a prefix: `feat:` for something new, `fix:` for a bug, and `docs:`, `refactor:`, `test:`, `ci:` or `chore:` for the rest. Then a short sentence in the imperative, for example `feat: add a name step to the wizard`. Version numbers and release notes are built from these.
- Do not add `Co-Authored-By` lines or tool attribution to commits or PR descriptions.
- Fill in the pull request template. Say what you could not test (another OS, real hardware). That is as useful as what you did.
- Anything that changes how the wizard, dashboard or `install.sh` looks or behaves should come with a short plan or a screenshot (demo data only) first.

## Rules

**Never leak**
- No personal values in code, tests, docs or screenshots: names, places, emails, hostnames, IPs. Use `example.com`, `192.168.1.20`, `10.0.0.5` and the fake demo data (`demo/generate.py`, fixed seed, obviously fake names).
- Never commit data, env files, tokens or anything in `private/` or `.private/`. `.gitignore` blocks them. Do not force-add.
- Never commit with `--no-verify`. If a check fails, fix the cause.

**Behaviour**
- Refactors keep behaviour. The golden API tests and bot router tests decide. Keep them green.
- Budget calculations are frozen. Moving code is fine. Open an issue first if you think one is wrong, and wait for the maintainer's yes.
- Optional features (Ollama, Whisper, Telegram, calendar, internet) must never crash when their dependency is missing. Show a clear message with a fix, never a raw traceback.
- Pin every image to an exact version (`scripts/check-pins.py` enforces it). No `:latest`.
- Do not add a new top-level dependency without a clear need. The only Python package today is PyYAML.
- Keep heavy jobs (image builds, model downloads, load tests) off any live server.

**What to ask people during install and setup**
- Needed for it to run (Docker, Homebrew on a Mac, build tools): install it directly, and say what and why. Do not ask.
- Needed for it to run properly, or clearly better for everyone (the host helper, starting again after a restart): install or turn it on directly. Say what it does and how to turn it off.
- Extras and preferences (optional apps, the `homelab` command on the PATH, opening it to the home network, a name): offer them as a choice. The default is what most people want.

**Style**
- No em dashes anywhere (code comments, docs, UI text, commits). Use commas or parentheses.
- Times shown to people are 12-hour (4:30 AM).
- Pills, tags and badges are never italic and never touch the text next to them.
- Every UI size, colour, radius and spacing comes from the design tokens (`tokens.css`). No raw px, rem or hex values in components. `make check` fails if they creep in.
- Match the surrounding code: naming, comment density, idiom.

More: [docs/ANTIPATTERNS.md](docs/ANTIPATTERNS.md) lists mistakes that have already happened once, [docs/modules.md](docs/modules.md) shows how to build a module in 15 minutes, and [docs/HANDOFF.md](docs/HANDOFF.md) describes how the project is put together and what is not yet verified.
