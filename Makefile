UV ?= uv
PNPM ?= pnpm
export PYTHONPATH := src:tests

MODEL_TESTS := tests/test_provider_catalog.py tests/test_provider_runtime.py \
	tests/test_provider_adapters.py tests/test_provider_surface.py tests/test_provider_settings.py \
	tests/test_provider_network.py tests/test_translation_client.py tests/test_chat_wait_policy.py

.PHONY: check backend-check lint test-models web-check test package

# Fast development/PR gate. Real inference is never part of these tests.
check: backend-check web-check

backend-check: lint test-models

lint:
	$(UV) run --frozen --extra dev ruff check src tests alembic
	$(UV) run --frozen --extra dev ruff format --check src tests alembic
	$(UV) lock --check --offline

test-models:
	$(UV) run --frozen --extra dev pytest -q $(MODEL_TESTS)

web-check:
	$(PNPM) --dir web test
	$(PNPM) --dir web build

# Full media/integration gate; use an isolated disposable PostgreSQL server.
test:
	@test -n "$$VT_TEST_POSTGRES_ADMIN_URL" || { printf '%s\n' 'Set VT_TEST_POSTGRES_ADMIN_URL to a disposable test PostgreSQL server.' >&2; exit 2; }
	$(UV) run --frozen --extra dev pytest -q

package:
	$(UV) build
