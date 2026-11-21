PYTHON ?= python3
export PYTHONPATH := src

.PHONY: test demo serve check all clean

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

demo:
	$(PYTHON) -m fda.demo

serve:
	$(PYTHON) -m fda

check:
	$(PYTHON) scripts/check.py

all: test demo check
