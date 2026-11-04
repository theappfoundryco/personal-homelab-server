"""Release and image plumbing, checked as files: pinned images, optional Watchtower, workflows that are valid and cautious, release and Renovate config.
GitHub itself is not involved, so whether a workflow runs there is verified on the first real push, not here."""
import glob
import json
import os
import re
import tempfile
import unittest

import yaml

import harness  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts")


def load_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_pins", os.path.join(CHECK, "check-pins.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def workflow(name):
    return yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", name)))


def triggers(wf):
    return wf.get("on") if "on" in wf else wf.get(True)  # YAML 1.1 reads a bare `on` as true


class Pins(unittest.TestCase):
    def test_the_repository_has_no_floating_images(self):
        self.assertEqual(load_check().problems(ROOT), [])

    def test_the_checker_catches_floating_ones_and_skips_built_images(self):
        mod = load_check()
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "stack"))
        open(os.path.join(d, "stack", "compose.yaml"), "w").write(
            "services:\n  a: {image: foo/bar:latest}\n  b: {image: foo/bar}\n  c: {image: foo/bar:2}\n  d: {image: ghcr.io/x/y:main}\n"
            "  e: {image: foo/bar:1.2.3}\n  f: {image: foo/bar:v1.2.3-alpine}\n  g: {image: foo/bar@sha256:abc}\n  h: {image: local:dev, build: .}\n  i: {image: foo/bar:alpine}\n")
        open(os.path.join(d, "Dockerfile"), "w").write("FROM python:3\nFROM python:3.12-slim\nFROM scratch\n")
        found = mod.problems(d)
        text = " | ".join(found)
        for bad in ("a uses foo/bar:latest", "b uses foo/bar,", "c uses foo/bar:2,", "d uses ghcr.io/x/y:main", "i uses foo/bar:alpine", "FROM python:3 is"):
            self.assertRegex(text, re.escape(bad).replace(",", "[, ]"))
        self.assertEqual(len(found), 6)  # a, b, c, d, i and the bare python:3
        for good in ("e uses", "f uses", "g uses", "h uses", "python:3.12-slim", "scratch"):
            self.assertNotIn(good, text)

    def test_watchtower_only_runs_when_asked_for(self):
        svc = yaml.safe_load(open(os.path.join(ROOT, "stack", "compose.yaml")))["services"]
        self.assertEqual(svc["watchtower"]["profiles"], ["auto-update"])
        others = [n for n, s in svc.items() if n != "watchtower" and s.get("profiles")]
        self.assertEqual(others, [])

    def test_python_packages_in_the_image_are_pinned(self):
        for line in open(os.path.join(ROOT, "stack", "telegram", "requirements.txt")).read().split():
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==\d+(\.\d+)+$")
        self.assertIn("-r /tmp/requirements.txt", open(os.path.join(ROOT, "stack", "telegram", "Dockerfile")).read())


class Workflows(unittest.TestCase):
    def files(self):
        return sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))

    def test_every_workflow_is_valid_with_read_only_defaults(self):
        self.assertTrue(self.files())
        for f in self.files():
            wf = yaml.safe_load(open(f))
            self.assertTrue(wf.get("jobs"), f)
            self.assertEqual(wf.get("permissions"), {"contents": "read"}, f"{f}: top-level permissions must be read only")
            self.assertTrue(triggers(wf), f)

    def test_actions_are_versioned_and_run_steps_never_embed_event_text(self):
        for f in self.files():
            text = open(f).read()
            for use in re.findall(r"uses:\s*(\S+)", text):
                if not use.startswith("./"):
                    self.assertRegex(use, r"@\S+$", f"{f}: {use} must name a version")
                    self.assertNotRegex(use, r"@(main|master|latest)$")
            for block in re.findall(r"run:\s*(?:\|\n((?:[ ]{10,}.*\n?)+)|(.*))", text):
                body = "".join(block)
                self.assertNotRegex(body, r"\$\{\{\s*(github\.event|inputs\.)", f"{f}: pass event text through env, not into the script")

    def test_only_the_image_job_may_write_packages_or_sign(self):
        for f in self.files():
            for name, job in yaml.safe_load(open(f))["jobs"].items():
                perms = job.get("permissions") or {}
                if perms.get("packages") == "write" or perms.get("id-token") == "write":
                    self.assertIn(os.path.basename(f), ("images.yml", "cut-release.yml"))
                self.assertNotIn("write-all", str(perms))
                if os.path.basename(f) != "cut-release.yml":
                    self.assertNotEqual(perms.get("contents"), "write", f)

    def test_images_are_multi_arch_signed_with_an_sbom_and_stay_unpushed_on_pull_requests(self):
        text = open(os.path.join(ROOT, ".github", "workflows", "images.yml")).read()
        wf = workflow("images.yml")
        self.assertIn("linux/amd64,linux/arm64", text)
        for must in ("sbom: true", "provenance:", "cosign sign --yes", "id-token: write", "type=raw,value=stable", "type=edge,branch=main"):
            self.assertIn(must, text)
        self.assertEqual({m["image"] for m in wf["jobs"]["build"]["strategy"]["matrix"]["include"]}, {"core", "web"})
        for m in wf["jobs"]["build"]["strategy"]["matrix"]["include"]:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, m["dockerfile"])), m["dockerfile"])
        self.assertIn("github.event_name != 'pull_request'", text)
        self.assertIn("workflow_call", triggers(wf))

    def test_a_release_is_cut_when_the_version_changes_on_main_and_only_then_are_images_built(self):
        wf = workflow("cut-release.yml")
        on = triggers(wf)
        self.assertEqual((on["push"]["branches"], on["push"]["paths"]), (["main"], ["core/version.py"]))
        self.assertEqual(wf["permissions"], {"contents": "read"})
        self.assertEqual(wf["jobs"]["release"]["permissions"], {"contents": "write"})  # only the job that tags may write
        self.assertIn("new == 'true'", wf["jobs"]["images"]["if"])
        self.assertEqual((wf["jobs"]["images"]["needs"], wf["jobs"]["images"]["uses"]), ("release", "./.github/workflows/images.yml"))
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".github", "workflows", "release.yml")))  # release-please is gone

class Config(unittest.TestCase):
    def test_the_release_script_tags_only_a_new_higher_version_and_writes_notes_by_kind(self):
        import importlib.util, shutil, subprocess
        d = tempfile.mkdtemp()
        g = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, text=True)
        g("init", "-q", "-b", "main"); g("config", "user.email", "t@example.com"); g("config", "user.name", "t")
        os.makedirs(os.path.join(d, "core")); os.makedirs(os.path.join(d, "scripts"))
        shutil.copy(os.path.join(ROOT, "core", "release_notes.py"), os.path.join(d, "core"))
        shutil.copy(os.path.join(ROOT, "scripts", "release.py"), os.path.join(d, "scripts"))
        open(os.path.join(d, "core", "__init__.py"), "w").close()
        def bump(v, *msgs):
            for m in msgs:
                open(os.path.join(d, "f.txt"), "a").write(m); g("add", "-A"); g("commit", "-q", "-m", m)
            open(os.path.join(d, "core", "version.py"), "w").write(f'VERSION = "{v}"\n'); g("add", "-A"); g("commit", "-q", "-m", f"release: {v}")
        run = lambda *a: subprocess.run(["python3", os.path.join(d, "scripts", "release.py"), *a], cwd=d, capture_output=True, text=True)
        bump("0.1.0", "feat: the start")
        self.assertEqual(run("check").stdout, "tag=v0.1.0\nnew=true\n")
        g("tag", "v0.1.0")
        self.assertEqual(run("check").stdout, "tag=v0.1.0\nnew=false\n")  # already released: nothing to do
        bump("0.2.0", "feat: add medicines", "fix: stop a crash", "security: lock the PIN", "docs: typo", "Merge branch x")
        self.assertIn("Merging this makes release v0.2.0", run("preview").stdout)
        g("tag", "v0.2.0")
        self.assertEqual(run("notes", "v0.2.0").stdout.strip(), "### Security\n- Lock the PIN.\n\n### New\n- Add medicines.\n\n### Fixed\n- Stop a crash.")
        bump("0.1.5")
        r = run("check")
        self.assertEqual(r.returncode, 1)  # a version that went down is refused
        self.assertIn("older than the newest release v0.2.0", r.stderr)

    def test_renovate_is_valid_and_guards_major_updates(self):
        cfg = json.load(open(os.path.join(ROOT, "renovate.json")))
        self.assertIn("helpers:pinGitHubActionDigests", cfg["extends"])
        rules = cfg["packageRules"]
        self.assertTrue(any(r.get("matchUpdateTypes") == ["major"] and r.get("dependencyDashboardApproval") for r in rules))
        for r in rules:
            if "versioning" in r:
                self.assertTrue(re.compile(r["versioning"].split("regex:", 1)[1].replace("(?<", "(?P<")).match("2026.11.2-d138f443b"))

    def test_no_em_dashes_in_the_new_files(self):
        dash = chr(0x2014)
        for rel in ("renovate.json", "scripts/release.py", "core/release_notes.py", "scripts/check-pins.py", "stack/compose.yaml", "stack/landing/Dockerfile", "stack/telegram/Dockerfile",
                    ".github/workflows/images.yml", ".github/workflows/cut-release.yml", ".github/workflows/ci.yml"):
            self.assertNotIn(dash, open(os.path.join(ROOT, rel)).read(), rel)


if __name__ == "__main__":
    unittest.main()
