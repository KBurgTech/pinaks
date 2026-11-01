from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone


def enqueue_existing(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    emails = apps.get_model("notifications", "OutgoingEmail")
    work = apps.get_model("workers", "WorkItem")
    alias = schema_editor.connection.alias
    for email in emails.objects.using(alias).filter(delivery_state="queued").iterator():
        work.objects.using(alias).get_or_create(
            job_type="notifications.deliver",
            identity=str(email.pk),
            defaults={
                "scheduled_at": email.scheduled_at,
                "created_at": timezone.now(),
                "updated_at": timezone.now(),
            },
        )


SQL = """
CREATE FUNCTION protect_delivery_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'delivery attempts cannot be deleted';
    END IF;
    IF OLD.outcome <> 'sending' OR NEW.email_id <> OLD.email_id
       OR NEW.started_at <> OLD.started_at OR NEW.id <> OLD.id THEN
        RAISE EXCEPTION 'delivery attempt evidence is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_delivery_attempt BEFORE UPDATE OR DELETE
ON notifications_deliveryattempt FOR EACH ROW EXECUTE FUNCTION protect_delivery_attempt();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0005_deliveryattempt"),
        ("workers", "0002_remove_workitem_work_running_has_lease_and_more"),
    ]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER protect_delivery_attempt ON notifications_deliveryattempt; DROP FUNCTION protect_delivery_attempt();",
        ),
        migrations.RunPython(enqueue_existing, migrations.RunPython.noop),
    ]
