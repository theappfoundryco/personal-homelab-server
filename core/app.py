"""What a module is handed when it starts: the shared pieces, and nothing else."""


class App:
    def __init__(self, config, router, scheduler, caps, store, llm=None, telegram=None, intents=None):
        self.config, self.router, self.scheduler, self.caps = config, router, scheduler, caps
        self.store, self.llm, self.telegram = store, llm, telegram
        self.intents = intents if intents is not None else {}  # name -> function(text) -> reply, for the bot's router
