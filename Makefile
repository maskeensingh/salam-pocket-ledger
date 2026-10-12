SALAM ?= salam
CC = clang

.PHONY: build test format-check

build:
	mkdir -p build
	$(SALAM) build main.salam --output=build/pocket-ledger --cc=$(CC) --log-level=error

test: build
	$(SALAM) build tests/unit.salam --output=build/unit --cc=$(CC) --log-level=error
	./build/unit
	python3 -m unittest discover -s tests -v

format-check:
	$(SALAM) format --check main.salam src/ tests/unit.salam
