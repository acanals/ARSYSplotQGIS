PLUGIN_NAME := ARSYSplotQGIS
VERSION := $(shell sed -n 's/^version=//p' metadata.txt | head -1)
OUT := dist/$(PLUGIN_NAME).$(VERSION).zip

.PHONY: zip clean

# Versioned package for plugins.qgis.org / dist/ repository.
# The Analytics hub picks the highest ARSYSplotQGIS.X.Y.Z.zip in dist/
# (see versions.json inventory). No .latest.zip.
zip:
	mkdir -p dist
	rm -f $(OUT)
	cd .. && zip -r $(PLUGIN_NAME)/$(OUT) $(PLUGIN_NAME) \
		-x '$(PLUGIN_NAME)/__pycache__/*' \
		-x '$(PLUGIN_NAME)/**/__pycache__/*' \
		-x '$(PLUGIN_NAME)/*.pyc' \
		-x '$(PLUGIN_NAME)/.git/*' \
		-x '$(PLUGIN_NAME)/.git/**' \
		-x '$(PLUGIN_NAME)/.gitignore' \
		-x '$(PLUGIN_NAME)/dist/*' \
		-x '$(PLUGIN_NAME)/dist/**' \
		-x '$(PLUGIN_NAME)/PUBLISH.md' \
		-x '$(PLUGIN_NAME)/Makefile' \
		-x '$(PLUGIN_NAME)/scripts/*' \
		-x '$(PLUGIN_NAME)/scripts/**' \
		-x '$(PLUGIN_NAME)/.idea/*' \
		-x '$(PLUGIN_NAME)/.idea/**' \
		-x '$(PLUGIN_NAME)/.vscode/*' \
		-x '$(PLUGIN_NAME)/.vscode/**' \
		-x '$(PLUGIN_NAME)/.cursor/*' \
		-x '$(PLUGIN_NAME)/.cursor/**'
	@if unzip -l $(OUT) | grep -E -q '(^|[[:space:]])($(PLUGIN_NAME)/)?(PUBLISH\.md|Makefile)([[:space:]]|$$)'; then \
		echo "ERROR: PUBLISH.md or Makefile found inside $(OUT)"; \
		unzip -l $(OUT) | grep -E 'PUBLISH\.md|Makefile'; \
		exit 1; \
	fi
	rm -f dist/$(PLUGIN_NAME).latest.zip
	$(MAKE) --no-print-directory versions-json
	@echo "Built $(OUT)"
	@unzip -l $(OUT) | tail -n +4 | head -n -2

# Inventory of versioned ZIPs in dist/ (for the Analytics hub Download button).
.PHONY: versions-json
versions-json:
	python3 scripts/write_versions_json.py

clean:
	rm -rf dist
