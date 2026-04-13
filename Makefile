.PHONY: test smoke lint install

install:
	pip install -e ".[dev]"

test:
	pytest -v

smoke:
	python -m pixel_forge generate \
		--project sunny-street \
		--kind tile \
		--prompt "solid red square" \
		--variants 2

lint:
	python -m compileall tools/pixel_forge
