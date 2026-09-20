import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pinaks.apps.accounts.models import User, UserRole


class Command(BaseCommand):
    help = "Create the protected local administrator from environment variables."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        existing = User.objects.select_for_update().filter(is_protected=True).first()
        if existing is not None:
            self.stdout.write("A protected local administrator already exists; no changes made.")
            return

        username = self._required_environment_value("PINAKS_BOOTSTRAP_ADMIN_USERNAME")
        email = self._required_environment_value("PINAKS_BOOTSTRAP_ADMIN_EMAIL")
        password = self._required_environment_value("PINAKS_BOOTSTRAP_ADMIN_PASSWORD")

        if User.objects.filter(username=username).exists():
            raise CommandError("The bootstrap administrator username is already in use.")
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("The bootstrap administrator email is already in use.")

        administrator = User(
            username=username,
            email=email,
            role=UserRole.ADMIN,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            is_protected=True,
        )
        try:
            validate_password(password, user=administrator)
        except ValidationError as error:
            raise CommandError("The bootstrap administrator password is not acceptable.") from error

        administrator.set_password(password)
        administrator.full_clean()
        administrator.save()
        self.stdout.write(self.style.SUCCESS("Created the protected local administrator."))

    @staticmethod
    def _required_environment_value(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise CommandError(f"{name} must be set.")
        return value
