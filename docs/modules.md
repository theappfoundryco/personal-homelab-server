# Build a module in 15 minutes

A module is a folder in `modules/` that adds one feature: a dashboard page, a bot command, a daily job. You never edit the core. If the module breaks, the rest of the app keeps running.

## 1. Copy the template

```bash
cp -r modules/_template modules/pets
```

Open `modules/pets/module.yaml` and change `name` to `pets` (it must match the folder name), plus the title and description.

## 2. Say what it needs

In `module.yaml`:

| Line | Meaning |
|---|---|
| `requires: [notes]` | Other modules it cannot work without. If one is off, yours is turned off with a clear note. |
| `optional: [ollama, internet]` | Things it can use if present. Missing ones never crash it (see step 4). |
| `platforms: [linux, mac, wsl]` | Remove a platform it cannot run on. It is hidden there with an explanation. |
| `default: false` | Off until the user switches it on. |
| `settings:` | What users can set in `config.yaml`. |
| `dashboard:` | The tab (`tab: {id, title, icon}`), home cards and the files of its views (`web: [view.js]`, served from `/m/<name>/web/`). Users can reorder, hide or switch these off in Settings. |

## 3. Write `__init__.py`

It has one function, `register(app)`. `app` gives you:

- `app.config.get("pets.name", "Rex")`: a setting, with a default.
- `app.router`: add dashboard pages.
  ```python
  @app.router.get("/pets")
  def pets(req):
      return {"pets": app.store.read("pets.json", [])}
  ```
- `app.scheduler`: add jobs. Times are in the user's timezone.
  ```python
  from core.scheduler import Job
  app.scheduler.add(Job("Feed reminder", remind, at=[(8, 0), (18, 30)]))
  ```
- `app.store`: read and write your own JSON files safely (a power cut never leaves half a file).
- `app.llm`: the Ollama client, if you need AI.
- `app.telegram`: send and edit messages.
- `app.intents`: bot commands, name to function.

## 4. Handle missing things politely

Wrap anything optional:

```python
app.caps.degrade("ollama", lambda: summarise(text))
```

If Ollama is down the user gets the fix message ("Start Ollama, or turn the AI features off") instead of an error. Pass `fallback="..."` to say something else.

## 5. Try it

Add `modules: {pets: true}` to `config.yaml` if it is off by default, restart, and open the dashboard. `make test` runs the checks (the template has a test you can copy).

## Rules for contributors

- No personal names, places or accounts in code. Everything personal is a setting.
- Times shown to people are 12-hour (4:30 AM).
- Sizes and colours come from the design tokens, never raw pixels.
- Say what to do when something is missing, never just "failed".
