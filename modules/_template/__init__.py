"""A module is a folder with module.yaml and this file. core calls register(app) once when the module starts."""


def register(app):
    greeting = app.config.get("hello.greeting", "Hello")

    # A page the dashboard can call: GET /hello
    @app.router.get("/hello")
    def hello(req):
        return {"message": f"{greeting}, {app.config.get('owner.name', 'friend')}!"}

    # A job: runs every day at 8:00 AM in the user's timezone
    from core.scheduler import Job
    app.scheduler.add(Job("Hello", lambda: None, at=[(8, 0)]))

    # Using something optional: if Ollama is missing the user gets the fix message, not a crash
    def smart():
        return app.caps.degrade("ollama", lambda: "The AI is ready.")

    app.intents["hello"] = lambda text: f"{greeting}! {smart()}"
