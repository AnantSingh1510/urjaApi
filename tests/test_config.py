import pytest
from pydantic import ValidationError

from urja_api.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://name:password@example.com",
        "https://example.com/path",
        "https://example.com?password=secret",
    ],
)
def test_config_rejects_unsafe_portal_origins(url):
    with pytest.raises(ValidationError):
        Settings(demo=True, base_url=url, _env_file=None)


def test_configuration_errors_do_not_dump_credentials():
    with pytest.raises(ValidationError) as error:
        Settings(username="", password="do-not-leak-this", _env_file=None)
    assert "do-not-leak-this" not in str(error.value)
