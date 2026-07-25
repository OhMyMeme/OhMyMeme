.PHONY: install run build build-windows build-linux build-installer clean test lint

# 开发命令
install:
	pip install -r requirements.txt

run:
	python -m src

test:
	python -m pytest tests/ -v

lint:
	ruff check src/
	black --check src/

format:
	black src/

# 打包命令 (Nuitka)
build:
	python scripts/build.py

build-windows:
	python scripts/build.py --windows

build-linux:
	python scripts/build.py --linux

build-installer:
	python scripts/build.py --installer-only

# 清理
clean:
	rm -rf dist/ build/ *.spec
	rm -rf src/__pycache__ src/*/__pycache__
	rm -rf .pytest_cache
