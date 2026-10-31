from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("documents", "0004_issuedartifact")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION documents_protect_artifact() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'Issued artifact metadata is immutable';
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER documents_protect_artifact_write
                    BEFORE UPDATE OR DELETE ON documents_issuedartifact
                    FOR EACH ROW EXECUTE FUNCTION documents_protect_artifact();

                CREATE FUNCTION documents_protect_finalization() RETURNS trigger AS $$
                BEGIN
                    IF OLD.lifecycle_status = 'ISSUED' AND NEW.lifecycle_status <> 'ISSUED' THEN
                        RAISE EXCEPTION 'Issued lifecycle cannot regress';
                    END IF;
                    IF NEW.lifecycle_status = 'ISSUED' AND OLD.lifecycle_status <> 'ISSUED' THEN
                        IF OLD.lifecycle_status <> 'ISSUING' OR
                           (SELECT count(*) FROM documents_issuedartifact WHERE invoice_id = NEW.id) <> 3 THEN
                            RAISE EXCEPTION 'Complete artifacts required for issuance';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER documents_protect_invoice_finalization
                    BEFORE UPDATE ON billing_invoice
                    FOR EACH ROW EXECUTE FUNCTION documents_protect_finalization();
            """,
            reverse_sql="""
                DROP TRIGGER documents_protect_invoice_finalization ON billing_invoice;
                DROP FUNCTION documents_protect_finalization();
                DROP TRIGGER documents_protect_artifact_write ON documents_issuedartifact;
                DROP FUNCTION documents_protect_artifact();
            """,
        ),
    ]
