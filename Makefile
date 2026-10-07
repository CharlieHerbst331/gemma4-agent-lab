.PHONY: setup check doctor package notebook
setup:
	uv sync --locked
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q
doctor:
	uv run gemma-lab doctor --online
package:
	uv run gemma-lab pack agents/baseline
notebook:
	uv run gemma-lab notebook agents/baseline --owner $${KAGGLE_USERNAME:?Set your Kaggle username}
