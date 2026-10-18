.PHONY: test example

test:
	python3 -m unittest discover -s tests -v
	node --test tests/*.test.mjs

example:
	python3 scripts/build_example_state.py
