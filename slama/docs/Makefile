# Build the SLAMA developer docs.  Run from slama/docs:  make html
SOURCE = source
BUILD  = _build

html:
	uv run sphinx-build -W --keep-going -b html $(SOURCE) $(BUILD)/html

# Rebuild and reload the browser on every save.
live:
	uv run sphinx-autobuild $(SOURCE) $(BUILD)/html

clean:
	rm -rf $(BUILD)

.PHONY: html live clean
