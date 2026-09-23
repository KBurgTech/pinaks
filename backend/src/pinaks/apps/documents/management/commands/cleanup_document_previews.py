from django.core.management.base import BaseCommand

from pinaks.apps.documents.preview_services import cleanup_expired_previews


class Command(BaseCommand):
    help = "Remove expired temporary document previews and their stored files."

    def handle(self, *args: object, **options: object) -> None:
        count = cleanup_expired_previews()
        self.stdout.write(f"Removed {count} expired document previews.")
