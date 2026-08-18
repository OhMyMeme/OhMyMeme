.PHONY: install run build build-installer clean test lint

# 开发命令
install:
	pip install -r requirements.txt

run:
	python -m ohmymeme

test:
	python -m pytest tests/ -v

lint:
	ruff check src/
	black --check src/

format:
	black src/

# 打包命令 (PyInstaller)
build:
	python scripts/build.py

build-installer:
	python scripts/build.py --installer-only

build-linux:
	bash scripts/installer/linux/build.sh all

# 清理
clean:
	rm -rf dist/ build/ *.spec
	rm -rf src/__pycache__ src/*/__pycache__
	rm -rf .pytest_cache
