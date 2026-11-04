"""How a module reaches things that still live in the app (send, location, B ...) without importing the app.
The app calls provide() once; each module calls need() for the names it uses. A missing name says exactly which one."""
_names = {}


def provide(**names):
    _names.update(names)


def need(module_globals, *names):
    """Put the named shared things into the module's globals. Raises with a clear message if the app has not provided one."""
    gone = [n for n in names if n not in _names]
    if gone:
        raise LookupError(f"the app has not provided: {', '.join(gone)}")
    module_globals.update({n: _names[n] for n in names})
