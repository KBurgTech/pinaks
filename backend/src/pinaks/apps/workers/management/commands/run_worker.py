import signal
from time import sleep
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from pinaks.apps.workers.registry import HANDLERS
from pinaks.apps.workers.services import run_one


class Command(BaseCommand):
    help = "Process database-backed work until stopped, or one cycle with --once."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=1.0)

    def handle(self, *args: Any, **options: Any) -> None:
        if options["poll_seconds"] <= 0:
            raise ValueError("poll-seconds must be positive")
        if options["once"]:
            run_one(handlers=HANDLERS)
            return
        stopping = False

        def stop(_signum: int, _frame: Any) -> None:
            nonlocal stopping
            stopping = True

        previous = signal.signal(signal.SIGTERM, stop)
        try:
            while not stopping:
                if not run_one(handlers=HANDLERS):
                    sleep(options["poll_seconds"])
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, previous)
