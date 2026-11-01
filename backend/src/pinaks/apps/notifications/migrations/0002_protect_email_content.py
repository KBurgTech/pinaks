from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
        CREATE FUNCTION notifications_protect_template() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' THEN
                RAISE EXCEPTION 'Published email versions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER notifications_template_write BEFORE UPDATE OR DELETE
            ON notifications_emailtemplateversion FOR EACH ROW
            EXECUTE FUNCTION notifications_protect_template();

        CREATE FUNCTION notifications_protect_snapshot() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Outgoing email content is immutable';
            END IF;
            IF (to_jsonb(NEW) - 'delivery_state') IS DISTINCT FROM
               (to_jsonb(OLD) - 'delivery_state') THEN
                RAISE EXCEPTION 'Outgoing email content is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER notifications_snapshot_write BEFORE UPDATE OR DELETE
            ON notifications_outgoingemail FOR EACH ROW
            EXECUTE FUNCTION notifications_protect_snapshot();
        """,
            reverse_sql="""
        DROP TRIGGER notifications_snapshot_write ON notifications_outgoingemail;
        DROP FUNCTION notifications_protect_snapshot();
        DROP TRIGGER notifications_template_write ON notifications_emailtemplateversion;
        DROP FUNCTION notifications_protect_template();
        """,
        )
    ]
