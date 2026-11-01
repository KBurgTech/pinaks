from typing import Any

from django.core.management.base import BaseCommand, CommandError

from pinaks.apps.documents.access import verify_issued_documents


class Command(BaseCommand):
    help = "Verify original issued bytes against stored hashes without regenerating evidence."

    def handle(self, *args: Any, **options: Any) -> None:
        # Django's command dispatch supplies dynamically typed args/options.
        unhealthy = verify_issued_documents()
        if unhealthy:
            raise CommandError(f"Issued document integrity failed for invoice IDs: {unhealthy}")
        self.stdout.write("All issued documents are healthy.")
