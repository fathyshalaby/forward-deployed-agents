PYTHON ?= python3
export PYTHONPATH := src:.

.PHONY: test demo tutorial install-skill serve api-serve integration-example check check-deploy scenarios all clean install \
        agents agents-list bundle-init bundle-validate bundle-build bundle-install \
        bundle-sign registry-init registry-publish approvals-ui ops-status audit-verify

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

demo:
	$(PYTHON) -m fda.demo

tutorial:
	$(PYTHON) -m fda tutorial

install-skill:
	$(PYTHON) scripts/install_skill.py

serve:
	$(PYTHON) -m fda serve

api-serve:
	$(PYTHON) -m fda api serve

integration-example:
	$(PYTHON) examples/integrations/product_app.py

check:
	$(PYTHON) scripts/check.py

check-deploy:
	$(PYTHON) scripts/check_deploy.py

scenarios:
	$(PYTHON) scripts/scenarios.py

agents:
	$(PYTHON) -m fda agents list

agents-list: agents

BUNDLE ?= examples/bundles/specky-fde
ARCHIVE ?= examples/bundles/dist/specky.customer-fde-0.1.0.fda
KEY ?= $(HOME)/.fda/keys/default.key
TRUST ?= $(HOME)/.fda/trust.json
REGISTRY ?= $(HOME)/.fda/registry
STATE ?= $(HOME)/.fda/state.db

bundle-init:
	$(PYTHON) -m fda agents init $(BUNDLE)

bundle-validate:
	$(PYTHON) -m fda agents validate $(BUNDLE)

bundle-build:
	$(PYTHON) -m fda agents build $(BUNDLE) -o $(ARCHIVE)

bundle-sign:
	$(PYTHON) -m fda agents build $(BUNDLE) -o $(ARCHIVE) --sign $(KEY)

registry-init:
	$(PYTHON) -m fda registry init --registry $(REGISTRY)

registry-publish:
	$(PYTHON) -m fda registry publish $(ARCHIVE) --registry $(REGISTRY) \
	  --trust $(TRUST) --keyfile $(KEY)

bundle-install:
	$(PYTHON) -m fda agents install $(ARCHIVE)

approvals-ui:
	$(PYTHON) -m fda approvals serve --state $(STATE)

ops-status:
	$(PYTHON) -m fda ops status --state $(STATE)

audit-verify:
	$(PYTHON) -m fda ops audit-verify --state $(STATE)

install:
	$(PYTHON) -m pip install .

all: test demo scenarios check check-deploy bundle-validate

clean:
	rm -rf build dist *.egg-info data/runtime/audit.jsonl
