"""Start the assistant: python -m core. Check it: python -m core doctor. See the machine: python -m core hardware. Update saved data: python -m core migrate"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HERE, os.path.join(HERE, "stack", "telegram")):  # intents.py: next to core/ in Docker, under stack/telegram in a checkout
    if os.path.isfile(os.path.join(p, "intents.py")) and p not in sys.path:
        sys.path.insert(0, p)

if __name__ == "__main__":
    if sys.argv[1:2] == ["hardware"]:  # what this machine is and which profile suits it; needs no config or data folder
        from core import hardware
        if sys.argv[2:3] == ["--save"] and len(sys.argv) > 3:  # the installer keeps what it saw, because the app in Docker sees only its own virtual machine
            hardware.save(sys.argv[3])
        print(hardware.render(hardware.view(data_dir=sys.argv[3] if sys.argv[2:3] == ["--save"] and len(sys.argv) > 3 else None)))
        sys.exit(0)
    if sys.argv[1:2] == ["migrate"]:  # saved-data changes a new version needs; update runs this, so it needs no config
        from core import migrations
        try:
            migrations.run_all(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("HL_DATA", "/data"))
        except (migrations.MigrationError, OSError) as e:
            sys.exit(f"Data migration stopped: {e}")
        sys.exit(0)
    from core import boot
    if sys.argv[1:2] == ["doctor"]:  # what is on, what is limited and how to fix it; exit 1 only if something is broken
        from core import doctor
        rep = boot.doctor()
        print(doctor.render(rep))
        sys.exit(0 if rep["ok"] else 1)
    elif sys.argv[1:]:
        sys.exit("Usage: python -m core [doctor|hardware|migrate]")
    boot.main()
