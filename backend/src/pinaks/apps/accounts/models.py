from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models.deletion import ProtectedError


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    COMPANY_MEMBER = "company_member", "Company Member"
    READ_ONLY = "read_only", "Read-Only"


class UserQuerySet(models.QuerySet["User"]):
    def delete(self) -> tuple[int, dict[str, int]]:
        protected_users: set[models.Model] = set(self.filter(is_protected=True))
        if protected_users:
            raise ProtectedError("A protected administrator cannot be deleted.", protected_users)
        return super().delete()

    def update(self, **kwargs: object) -> int:
        if self.filter(is_protected=True).exists():
            raise ValueError("A protected administrator cannot be changed or deactivated.")
        return super().update(**kwargs)


class UserManager(DjangoUserManager["User"]):
    def get_queryset(self) -> UserQuerySet:
        return UserQuerySet(model=self.model, using=self._db)

    def create_superuser(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: object,
    ) -> User:
        extra_fields.setdefault("role", UserRole.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    role: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=UserRole,
        default=UserRole.READ_ONLY,
    )
    is_protected: models.BooleanField[bool, bool] = models.BooleanField(default=False)

    objects = UserManager()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_protected=False)
                    | models.Q(
                        role=UserRole.ADMIN,
                        is_active=True,
                        is_staff=True,
                        is_superuser=True,
                    )
                ),
                name="protected_user_is_active_admin",
            )
        ]

    # Django's model persistence hook is an intentionally framework-owned dynamic boundary.
    def save(self, *args: Any, **kwargs: Any) -> None:
        was_protected = bool(
            self.pk and type(self).objects.filter(pk=self.pk, is_protected=True).exists()
        )
        if (self.is_protected or was_protected) and not (
            self.is_protected
            and self.role == UserRole.ADMIN
            and self.is_active
            and self.is_staff
            and self.is_superuser
        ):
            raise ValueError("A protected administrator cannot be changed or deactivated.")
        super().save(*args, **kwargs)

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        if self.is_protected:
            raise ProtectedError("A protected administrator cannot be deleted.", {self})
        return super().delete(using=using, keep_parents=keep_parents)
