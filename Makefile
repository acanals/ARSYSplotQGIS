PLUGIN_NAME := ARSYSplotQGIS
VERSION := $(shell sed -n 's/^version=//p' metadata.txt | head -1)
OUT := dist/$(PLUGIN_NAME).$(VERSION).zip

.PHONY: zip clean

zip:
	mkdir -p dist
	rm -f $(OUT)
	cd .. && zip -r $(PLUGIN_NAME)/$(OUT) $(PLUGIN_NAME) \
		-x '$(PLUGIN_NAME)/__pycache__/*' \
		-x '$(PLUGIN_NAME)/**/__pycache__/*' \
		-x '$(PLUGIN_NAME)/*.pyc' \
		-x '$(PLUGIN_NAME)/.git/*' \
		-x '$(PLUGIN_NAME)/.gitignore' \
		-x '$(PLUGIN_NAME)/dist/*' \
		-x '$(PLUGIN_NAME)/PUBLISH.md' \
		-x '$(PLUGIN_NAME)/.idea/*' \
		-x '$(PLUGIN_NAME)/.vscode/*'
	@echo "Built $(OUT)"

clean:
	rm -rf dist
