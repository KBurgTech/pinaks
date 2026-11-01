from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_alter_emailtemplateversion_published_at")]
    operations = [
        migrations.RunSQL(
            sql="""
        CREATE FUNCTION notifications_verify_provenance() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM documents_issuedartifact a JOIN billing_invoice i ON i.id = a.invoice_id
                WHERE a.id = NEW.attachment_id AND a.invoice_id = NEW.invoice_id
                  AND a.kind = 'pdf' AND a.sha256 = NEW.attachment_sha256
                  AND i.lifecycle_status IN ('ISSUED', 'CANCELLED')
            ) OR NOT EXISTS (
                SELECT 1 FROM notifications_emailtemplateversion v
                WHERE v.id = NEW.template_version_id AND v.status = 'published'
                  AND v.language = NEW.language
            ) THEN
                RAISE EXCEPTION 'Outgoing email provenance mismatch';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER notifications_snapshot_insert BEFORE INSERT
            ON notifications_outgoingemail FOR EACH ROW
            EXECUTE FUNCTION notifications_verify_provenance();
        """,
            reverse_sql="""
        DROP TRIGGER notifications_snapshot_insert ON notifications_outgoingemail;
        DROP FUNCTION notifications_verify_provenance();
        """,
        )
    ]
