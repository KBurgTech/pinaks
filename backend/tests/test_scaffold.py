from django.core.checks import run_checks


def test_django_configuration_has_no_system_check_errors() -> None:
    assert run_checks() == []
