import pytest
from django.core.checks import run_checks


@pytest.mark.django_db
def test_django_configuration_has_no_system_check_errors() -> None:
    assert run_checks() == []
