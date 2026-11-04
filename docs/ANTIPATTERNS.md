# Anti-patterns

Mistakes that already happened in this project, so they do not happen twice. Each one says what to do instead.

## Design and UI
- **Raw `px`, `rem` or hex values in a component.** Every size, colour, radius and spacing comes from `tokens.css`. Add or reuse a token. `make check` fails on raw values.
- **Icons or images sized by the container.** The setup wizard once stretched its icons. Give them a fixed token size.
- **Pills and badges touching the text beside them, or set in italic.** Keep a gap from the tokens and normal text style.
- **24-hour times, or dates in a fixed locale.** Show 12-hour times such as 4:30 AM.
- **Cards that collide or overflow on a narrow screen.** Check the phone width before you call a layout done.

## Installer and setup
- **Asking people about things the project needs to run.** Docker, Homebrew on a Mac and build tools are installed directly, with a line saying what and why. Ask only about optional extras.
- **A question after a long step has started.** Ask everything first, then do the work, so nothing waits behind a spinner. The browser opens last.
- **Output wider than the terminal.** A spinner line longer than the window wraps and stacks on every redraw. Fit lines to the width and never cut text inside brackets.
- **Editing `install.sh` while it runs.** Bash reads a script as it goes. The script lives inside a `main` function for this reason, but still do not edit a running one.
- **Raw logs on screen.** Long steps show a spinner. The full output goes to the install log and is printed only when a step fails.
- **Taking the hardware from inside Docker.** The app sees Docker's virtual machine, not the real machine. The installer saves the real hardware to a file.

## Code and behaviour
- **Touching budget maths.** It is frozen. Move code if you must, but any change to a calculation needs the maintainer's explicit yes, and the golden tests must still pass.
- **Crashing when an optional dependency is missing.** Ollama, Whisper, Telegram, the calendar and the internet can all be absent. Show a clear message with a fix and keep everything else working.
- **Showing a traceback to a user.** Catch it, log it, and say in plain words what to do.
- **Modules importing each other.** Modules talk to the core through `host.provide` and `host.need`.
- **Rewriting a test to match new output.** Golden API replies are recorded deliberately (`make update-golden`) and the diff is reviewed.
- **Adding a new top-level dependency for a small job.** The only Python package is PyYAML. Use the standard library unless there is a real need.

## Images and updates
- **`:latest` or an unpinned image tag.** Pin every image to an exact version. `scripts/check-pins.py` enforces it.
- **Accepting a major version bump unread.** n8n, Grafana and Open WebUI migrate their data on first start, and some cannot go back. Read the notes and take `homelab backup` first.
- **A commit sentence nobody outside the code understands.** Commit subjects are the release notes people read in the update popup. Use the right prefix (`security:`, `feat:`, `fix:`) and say what changes for them.
- **Auto-updating behind `homelab update`.** Watchtower is off by default because it moves pinned versions on its own.

## Privacy and safety
- **Personal values in code, defaults, comments, tests, docs or screenshots.** Names, places, hostnames, IPs and emails belong in `config.yaml` or `.env`. Tests and demos use obviously fake values (Alex, Testville).
- **Real values in `config.example.yaml` or `*.env.example`.** They are copied to every install. Use placeholders; your own values go in `config.yaml` and `.env`.
- **Real screenshots in the repo.** Screenshots come from the demo data (`demo/generate.py`) only.
- **Committing data, env files or backups.** The data guard blocks them. Do not force-add.
- **Bypassing a hook with `--no-verify`.** If a guard fails, fix the cause.
- **Printing the personal-value list** in a log, commit message, issue or PR.

## Process
- **Pushing to `main`.** Use a branch and a pull request.
- **Large pull requests that mix tasks.** One task per branch.
- **Acting on a guess.** Investigate, report, then fix.
- **Running heavy jobs on a server other things depend on.** Builds, model downloads and load tests run on a development machine.
