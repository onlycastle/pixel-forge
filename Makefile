.PHONY: test smoke lint install

install:
	pip install -e ".[dev]"

test:
	pytest -v

smoke:
	python -m pixel_forge generate \
		--project smoke-test \
		--kind tile \
		--prompt "solid red square" \
		--variants 2 \
		--output-json

lint:
	python -m compileall tools/pixel_forge
