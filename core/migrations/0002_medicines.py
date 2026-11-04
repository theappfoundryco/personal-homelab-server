"""Health: the fixed morning, lunch and night slots and the weekly courses become medicines with their own times (0.2.0). Ticks are kept."""
import importlib.util
import os
from datetime import date

from core import store

HERE = os.path.dirname(os.path.abspath(__file__))


def _meds():
    """modules/health/meds.py on its own: importing the package would start the Health module, which needs the running assistant."""
    spec = importlib.util.spec_from_file_location("_health_meds", os.path.join(HERE, "..", "..", "modules", "health", "meds.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(data_dir):
    path = os.path.join(data_dir, "sg.json")
    sg = store.read_json(path, None)
    if isinstance(sg, dict) and _meds().convert_old(sg, date.today()):
        store.write_json(path, sg)
