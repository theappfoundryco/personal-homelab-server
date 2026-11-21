"""What a module is handed when it starts: the shared pieces, and nothing else."""

# Where modules plug into the Telegram bot and the morning brief. One list each for the whole app: the bot and the brief read them.
TEXT_HOOKS = []  # fn(text, lowered) -> True when it answered the message; tried after the bot's own commands, before the AI classifier
TAPS = {}  # button data prefix -> fn(data, message), for the buttons a module sends
BRIEF_LINES = []  # fn() -> [(icon, NAME, [line, ...])], extra sections for the morning brief; [] when there is nothing to say


class App:
    def __init__(self, config, router, scheduler, caps, store, llm=None, telegram=None, intents=None):
        self.config, self.router, self.scheduler, self.caps = config, router, scheduler, caps
        self.store, self.llm, self.telegram = store, llm, telegram
        self.intents = intents if intents is not None else {}  # name -> function(text) -> reply, for the bot's router
        self.text_hooks, self.taps, self.brief_lines = TEXT_HOOKS, TAPS, BRIEF_LINES
