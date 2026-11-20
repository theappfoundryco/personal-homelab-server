# Review: the SohamDarekar fork

Fork: [SohamDarekar/personal-homelab-server](https://github.com/SohamDarekar/personal-homelab-server), branch `main`, 16 commits on top of our `main` at `5f80afb`, pushed 2026-11-17. No pull request has been opened to us. It is the only fork (checked 2026-11-21).

About 1,000 lines: mostly a new Nodes module (`modules/nodes/`, `tests/test_nodes.py`), plus small changes to `install.sh`, `stack/compose.yaml`, `stack/config.example.yaml`, `stack/prometheus/prometheus.yml`, the dashboard and `tests/test_release.py`.

## How it was checked

- Every commit was read in full.
- Its tests ran inside a throwaway `python:3.12-slim` container (PyYAML and ruff only), once per commit, in order on top of our `main`: unit tests, `check-tokens.py`, `check-pins.py`, `check-personal.py --all`, `check-needs.py`.
- Result: **all 16 commits pass**. The test count goes from 344 to 381. One run of the last commit showed one error; a rerun of that commit in a `python:3.12` container (with git) passed all 381, so it was a flaky run, not the commit.
- Not run: its installer, and the dashboard in a browser. Nothing from the fork was run on a real machine.

## Verdicts

| Commit | What it does | Verdict | Why |
|---|---|---|---|
| `e67a397` feat: let a module answer plain sentences in Telegram before the classifier (`app.text_hooks`) | A list of `fn(text, lowered)` hooks the bot tries before the AI classifier | **Take with changes** | A clean, small extension point, documented in `docs/modules.md`. Change: `core/boot.py` adds a `/nodes` command when the `nodes` module is on, so the core now knows a module by name. Modules should register their own bot commands. |
| `ebd9177` feat: accept a nodes list and node_limits in config.yaml | Schema for `nodes:` and `node_limits:` | **Take** (with the Nodes module) | Uses the existing schema, example values are fake (`192.168.1.20`, `10.0.0.5`), off by default. |
| `46bc3c0` feat: add the Nodes module | Live numbers from each machine's own Prometheus, Telegram answers, alerts once and once again when cleared | **Take with changes** | Good shape: short timeouts, one dead machine never blocks the others, never raises, plain messages, off by default, no new dependency. Changes: the temperature query only matches Intel `coretemp`, so AMD `k10temp` and Raspberry Pi `cpu_thermal` show nothing (our own `modules/server` has the same query, so fix both); disk is `/` only; the alert thread only starts if nodes existed at boot. |
| `1abfaaa` test: cover the Nodes module | 32 tests | **Take** | Real coverage of two machines, Telegram sentences, alerts and config. |
| `485145d` fix: keep the Health tab named Health and move the AI usage block off it | Removes the first-name tab label and the AI usage block from Health | **Decline** | It undoes a deliberate choice (the Health tab shows your first name, see HANDOFF) and overlaps with `d0a4b2d` on `release/0.3.0`, which already moves AI usage to Server and Apps. |
| `03871b9` feat: show every node on the Server and Apps page | Moves Nodes from its own tab onto Server and Apps, adds disks, load, swap, network | **Take with changes** | Useful detail. Changes: it moves AI usage too (conflicts with 0.3.0), and it switches the bars from `data-w` to inline `style="width:..."`. |
| `906564d` ci: build the images for amd64 only | Drops arm64 images and QEMU | **Decline** | Raspberry Pi and Apple silicon need arm64. If build time was the problem, use a native arm64 runner (`ubuntu-24.04-arm`), not fewer platforms. |
| `1a1f4e3` feat: scrape the GPU exporter in Prometheus | Adds a `gpu` job on `host.docker.internal:9835` | **Take with changes** | On every machine without that exporter, this shows as a target that is always down. Make it part of a GPU option, not the default config. |
| `fd67757` feat: let HL_GRAFANA_PORT move Grafana off port 3000 | `${HL_GRAFANA_PORT:-3000}` | **Take, then generalise** | Right idea, and it hits a real clash (3000 is busy on many machines). Every app port should get the same treatment, and the installer should check them before starting (see `docs/plans/platform-profile.md`). |
| `0365128` fix: let the assistant and Open WebUI reach an Ollama on the same Linux machine | `extra_hosts: host.docker.internal:host-gateway` on `telegram-bot` and `open-webui` | **Take as is** | A real bug on our `main`: `core/setup.py` and `core/apps.py` point at `host.docker.internal:11434` for an Ollama outside Docker, and Linux Docker Engine does not define that name. |
| `6259144` feat: open app tiles on the https port Tailscale serves them on (`dashboard.app_ports`) | Maps a tile's local port to an https port | **Take with changes** | Useful for anyone using `tailscale serve`. It is not Tailscale-specific in the code, so the comment and setting name should say "https port" without tying it to one product. |
| `469ff83` fix: point AI chat at the Ollama already on the machine | Writes `HL_OLLAMA_URL=http://host.docker.internal:11434` when the installer found one | **Take** (after `0365128`) | Correct and small. It depends on `0365128`, otherwise the address does not resolve on Linux. |
| `36730b7` feat: let your own tiles open in a new tab (`outside: true`) | One schema field | **Take** | The schema change is fine and tested. The dashboard already opens `outside` tiles in a new tab (`stack/landing/site/js/apps.js`, line 79); this lets your own tiles in `config.yaml` use it. |
| `a956169` fix: give Dozzle a data folder so its login can be turned on | `dozzle-data:/data` volume | **Take** | Small and correct. |
| `be5e760` fix: let the World Clock find the big Indian cities | Adds 9 cities to a hard-coded alias table | **Take with changes** | The bug is real (the time zone list only knows `Asia/Kolkata`). A city search that does not depend on one country's list is the better fix (see `docs/plans/generalise-regional-defaults.md`). Until then, this is harmless. |
| `09a8853` feat: show the other machines in Hardware specs and health | Processor, memory, disks, temperatures, network per node | **Take with changes** | Changes: `style="margin-top:8px"` is a raw size (use a token class); `toLocaleDateString('en-GB', ...)` fixes the locale. Both copy patterns already on our `main` (`shared.js`, `briefing.js`), so this is our debt too, not only the fork's. |

## Security notes

- No new port is opened. Nothing is bound outside `127.0.0.1`. The host helper's allowlist is not touched.
- New outgoing calls: the Nodes module asks each configured Prometheus and each `checks:` URL. Both come from your own `config.yaml`, and the dashboard reply leaves the addresses out (`public()`).
- `check_url` treats any answer below 500 as "up". Fine for a health check; it never sends credentials.

## Suggested order if the author opens pull requests

1. `0365128` + `469ff83` (a real Linux bug), as one PR.
2. `a956169` (Dozzle data folder).
3. `fd67757` (Grafana port), so it can be generalised to every port afterwards.
4. `e67a397` + `ebd9177` + `46bc3c0` + `1abfaaa` + `03871b9` + `09a8853` (the Nodes module), as one PR with the changes above and without the AI usage move.
5. `6259144`, `36730b7`, `1a1f4e3`, each on its own.

Declined: `485145d`, `906564d`.

## Draft message for the maintainer to send

> Hi Soham, thank you for the work in your fork. I read all 16 commits and ran your tests on each one; they all pass on our main.
>
> A few are ready to come in as they are, and I would love pull requests for them, so the history credits you: the `host-gateway` fix for Ollama on Linux together with the installer change that uses it, the Dozzle data folder, and the Grafana port setting.
>
> The Nodes module is great and I would like it too. Could you open it as one PR with a few changes: let the module register its own `/nodes` command instead of `core/boot.py` knowing about it, widen the temperature query beyond Intel `coretemp`, keep the bars on `data-w`, and leave the AI usage block where 0.3.0 puts it?
>
> Two I will not take: building images for amd64 only (people run this on Raspberry Pis and Apple silicon), and the change to the Health tab name (that one is on purpose).
>
> Thanks again. Small, focused PRs into `main` are easiest to review. CONTRIBUTING.md has the checks to run.
