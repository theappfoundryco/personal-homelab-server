# Plan: regional and personal defaults that should be settings

Status: plan only, nothing built. Needs the maintainer's yes, because it changes what the bot, the briefing and the journal AI say.

The project started as one person's assistant, and some of that person's world is still in the code: India news, India cricket alerts, rupees and Singapore dollars, Hindi family words, a fixed date locale, and AI instructions written about one man. For anyone else these are wrong defaults. Below, each one with where it lives today and what it should become.

## What is hard-coded today

| Where | What | Who it is wrong for |
|---|---|---|
| `modules/news/__init__.py`, `FEEDS["india"]`, `TOPIC_NAMES`, `TOPIC_WORDS` | An India topic with three Indian papers; Mint as the markets feed; cricket words (`ipl`, `bcci`, players) | Anyone outside India |
| `modules/briefing/__init__.py` lines 57 and 58, 118, 186 | India and Cricket buttons; "World, India and F1 news" in every briefing | Anyone outside India, anyone who does not follow cricket or F1 |
| `modules/sports/__init__.py` (`INDIA` regex), `modules/alerts/__init__.py` lines 97 to 122 | Live alerts only for India cricket matches | Every other team and sport |
| `modules/currency/__init__.py` lines 12 to 59 | Home currency is INR; SGD is the default second currency; rates are shown "only when away from India" | Everyone not living in India with ties to Singapore |
| `modules/journal/__init__.py` lines 202 to 235 | Hindi family words with their meanings | People who do not write in Hindi or Indian English (it is harmless, but it is one language picked for everyone) |
| `core/chat.py` line 19, `modules/journal/__init__.py` lines 27 to 37 and 167 to 171, `modules/briefing/__init__.py` line 161 | AI instructions say "he" and "his", and describe one person's life | Everyone else, and it reads oddly in a public project |
| `stack/landing/site/js/shared.js` lines 11 and 14, `briefing.js` line 52, `planner.js` line 65 | Dates formatted with `en-GB` | Against the project's own rule (dates never in a fixed locale) |
| `modules/health/web/view.js` line 168 | Numbers formatted with `en-IN` (1,00,000) | Everyone outside South Asia |
| `stack/landing/site/js/home.js` `CLK_ALIAS` | World Clock aliases; the fork adds Indian cities to it | A list per country never ends |

## What it should become

1. **One `region:` block in `config.yaml`**, filled by the setup wizard from the time zone it already asks for, editable in Settings:
   ```yaml
   region:
     country: ""          # ISO code, e.g. "GB". Empty: taken from the time zone
     currency: ""         # e.g. "GBP". Empty: the country's currency
     also_currencies: []  # shown in the briefing when you are away, e.g. ["USD"]
     languages: []        # extra languages your journal uses, e.g. ["hi"]
   ```
2. **News topics as data, not code.** Move `FEEDS` into `modules/news/feeds.yaml` with a `regions:` section (a few well-known RSS feeds per country, starting with the ones in the code today under `IN`). The briefing shows "World" plus your country's topic, named after the country. People can add their own feeds under `news.feeds` in `config.yaml`.
3. **Sports by choice.** `sports.follow: [f1, "cricket:India"]` style settings, empty by default. The alert loop only runs for what you follow. The cricket regex takes the team name from the setting.
4. **Currency from the region.** `in_india()` becomes "at home", using the configured country. The pair defaults to home currency plus `also_currencies`.
5. **Journal language packs.** Move the Hindi family words to `modules/journal/lang/hi.yaml`, used only when `region.languages` lists `hi`. Others can add a pack the same way.
6. **AI instructions written for anyone.** Use the person's first name from Settings, and "they" when there is none (or a pronoun setting, if the maintainer prefers). Instructions about one person's life move to an optional, private `journal.notes_for_ai` setting that stays on that person's machine. This needs a careful read of every prompt, and the golden tests re-recorded and reviewed.
7. **Dates and numbers in the viewer's locale.** Replace `'en-GB'` and `'en-IN'` with `undefined` (the browser's locale) while keeping 12-hour times (`hour12: true`, the `T12` object).
8. **World Clock search, not a list.** Search `Intl.supportedValuesOf('timeZone')` by city name and fall back to a small built-in alias table for cities that are not a zone name (most big cities are not). This replaces the fork's India list and the US and Europe ones.

## Order, if approved

1. Locales (7): small, no behaviour change except formatting. Check the phone-width screenshots.
2. Region block (1) and currency (4).
3. News feeds as data (2) and sports (3). Golden tests re-recorded.
4. AI instructions (6) and language packs (5). Needs the maintainer to read every prompt change.

## Not decided (questions for the maintainer)

- Should the defaults for a new install be "no country topic" or "your country's topic"?
- Pronouns: first name and "they", or a setting?
