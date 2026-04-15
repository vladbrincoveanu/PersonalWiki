import pytest
from unittest.mock import MagicMock, patch

# Prevent LanceDB segfaults in tests by mocking get_store early
_mock_store = MagicMock()
_mock_store.get_all_paths.return_value = []
# Patch at the source module where it's defined
patcher = patch("core.vector_store.get_store", return_value=_mock_store)
patcher.start()


@pytest.fixture(autouse=True)
def mock_vector_store():
    """Ensure get_store always returns a mock."""
    return _mock_store
