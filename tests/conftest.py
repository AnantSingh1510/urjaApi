import pytest
from fastapi.testclient import TestClient

from urja_api.app import create_app
from urja_api.config import Settings
from urja_api.demo import DemoPortal


@pytest.fixture
def settings():
    return Settings(demo=True, _env_file=None)


@pytest.fixture
def portal():
    return DemoPortal()


@pytest.fixture
def client(settings, portal):
    with TestClient(create_app(settings, portal)) as client:
        yield client
