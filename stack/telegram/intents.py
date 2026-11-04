"""Labelled examples for the bot's intent classifier (nearest neighbours on sentence embeddings).
Add a line here whenever the bot misreads something; no code changes needed."""

EXAMPLES = {
    "answer": [
        "Tell me about Max Verstappen's 2026 season in F1", "how is Leclerc doing this year", "who won the last race",
        "how many wins does Antonelli have", "who is leading the championship", "what happened at the Singapore grand prix",
        "how is India doing in the match", "what's the score in the india game", "who is the CEO of Nvidia", "what's bitcoin at",
        "price of gold today", "how are the markets doing", "explain how rain forms", "what is a CPU", "how does a vaccine work",
        "what is the capital of Australia", "when is the iPhone Duo coming out", "is the new Zelda game out yet",
        "what is the population of Tokyo", "compare iPhone and Pixel cameras", "who is Satya Nadella",
        "what is the Paris Agreement", "why did Red Bull struggle this season", "how tall is the Burj Khalifa",
        "best pizza in Naples", "what's the best laptop for programming", "how did Kohli do in the last series",
        "what time is it in London", "when was Google founded", "is Mercedes faster than McLaren this year",
    ],
    "chat": [
        "tell me a joke", "thanks!", "thank you", "good night", "how are you", "write a birthday message for my dad",
        "write a short thank you note to my manager", "help me reply to this email politely", "what should I eat for dinner",
        "give me a motivational quote", "I'm feeling stressed", "translate hello into hindi", "what's 18% of 64",
        "suggest a name for my cat", "what should I pack for Berlin", "ok", "cool", "lol", "you're awesome",
        "rewrite this to sound more professional", "summarise what we talked about",
    ],
    "server": [
        "is my server ok", "is everything ok with the server", "how hot is the cpu", "server status", "how is the homelab",
        "are my websites up", "is anything down", "stats", "how much ram is used", "disk space", "server health",
    ],
    "restart_app": ["restart n8n", "restart the ai chat", "restart ollama", "reboot the website monitor", "restart grafana"],
    "logs": ["show me n8n logs", "logs", "logs for ollama", "what's n8n doing"],
    "free_ai_memory": ["free up ram", "unload the ai", "free ai memory", "clear the model from memory"],
    "reboot_server": ["reboot the server", "restart the server", "restart the homelab"],
}
