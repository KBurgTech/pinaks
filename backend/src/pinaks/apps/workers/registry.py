from pinaks.apps.documents.issuance import handle_generation
from pinaks.apps.notifications.delivery import handle_delivery
from pinaks.apps.workers.services import Handler

HANDLERS: dict[str, Handler] = {
    "documents.generate": handle_generation,
    "notifications.deliver": handle_delivery,
}


def run_registered_once() -> bool:
    from pinaks.apps.notifications.delivery import reconcile_deliveries
    from pinaks.apps.workers.services import run_one

    reconcile_deliveries()
    return run_one(handlers=HANDLERS)
