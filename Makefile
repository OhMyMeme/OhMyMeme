.PHONY: install run build clean test lint

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

# 打包命令
build:
	python scripts/build.py --onefile

build-dir:
	python scripts/build.py --onedir

build-windows-installer:
	# 需要 Inno Setup (iscc) 在 PATH 中
	iscc scripts/installer/windows.iss

build-linux:
	bash scripts/installer/linux/build.sh all

# 清理
clean:
	rm -rf dist/ build/ *.spec
	rm -rf src/__pycache__ src/*/__pycache__
	rm -rf .pytest_cache
