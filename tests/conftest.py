import pytest

from botmap import core


@pytest.fixture(autouse=True)
def _fresh_dataset_cache():
    """Each test opens its own dataset; a cached fake must not leak into the next."""
    core._open_dataset_cached.cache_clear()
    yield
    core._open_dataset_cached.cache_clear()
