.PHONY: hooks check test test-e2e update-baselines update-golden
hooks:  ## enable the pre-commit and pre-push guards
	git config core.hooksPath .githooks
	@if [ -s .private/denylist.txt ]; then git config homelab.maintainer true; echo "Maintainer mode: the personal denylist is required."; fi
	@command -v gitleaks >/dev/null || echo "Install gitleaks: brew install gitleaks (or see https://github.com/gitleaks/gitleaks)"
check:  ## scan the whole tree
	scripts/check-data-guard.sh --all
	scripts/check-denylist.sh --all
	python3 scripts/check-personal.py --all
	python3 scripts/check-tokens.py
	python3 scripts/check-pins.py
test:  ## golden API tests and bot router tests (needs python3 and pyyaml)
	cd tests && PYTHONPATH=. python3 -W ignore -m unittest discover -s . >/dev/null
test-e2e:  ## dashboard smoke tests on demo data (pip install playwright pyyaml; playwright install chromium)
	cd tests && PYTHONPATH=. python3 -W ignore -m unittest e2e.test_dashboard
update-baselines:  ## re-record the phone-width screenshots (review them before committing)
	cd tests && UPDATE_BASELINES=1 PYTHONPATH=. python3 -W ignore -m unittest e2e.test_dashboard
update-golden:  ## re-record the golden API replies (review the git diff before committing)
	cd tests && UPDATE_GOLDEN=1 PYTHONPATH=. python3 -W ignore -m unittest test_golden_api
