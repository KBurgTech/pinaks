from pinaks.apps.documents.issuance import handle_generation
from pinaks.apps.workers.services import Handler

HANDLERS: dict[str, Handler] = {"documents.generate": handle_generation}
