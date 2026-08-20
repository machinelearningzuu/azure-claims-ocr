# A root-level conftest.py makes pytest add this directory to sys.path, so
# tests can `import app.…` without any install step.
#
# It also points the app at a throwaway database BEFORE any app module is
# imported (the engine is created at import time), so tests never touch the
# real claims.db. load_dotenv() does not override variables that already
# exist, so this wins over .env.

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_claims.db")

import pathlib  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _remove_test_db_after_run():
    yield
    pathlib.Path("test_claims.db").unlink(missing_ok=True)
