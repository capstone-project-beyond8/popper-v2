import os

import pytest

# Each child script otherwise allocates per-core BLAS buffers; parallel runs exhaust memory.
for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(name, "1")


@pytest.fixture(autouse=True)
def _key_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPER_KEY_DIR", str(tmp_path_factory.mktemp("keys")))
