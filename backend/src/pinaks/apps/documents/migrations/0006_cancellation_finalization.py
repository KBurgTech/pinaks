from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0005_protect_issued_evidence"),
        ("billing", "0014_cancellation_protection"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""CREATE OR REPLACE FUNCTION documents_protect_finalization() RETURNS trigger AS $$
                BEGIN
                    IF OLD.lifecycle_status = 'ISSUED' AND NEW.lifecycle_status NOT IN ('ISSUED', 'CANCELLED') THEN
                        RAISE EXCEPTION 'Issued lifecycle cannot regress';
                    END IF;
                    IF NEW.lifecycle_status = 'ISSUED' AND OLD.lifecycle_status <> 'ISSUED' THEN
                        IF OLD.lifecycle_status <> 'ISSUING' OR
                           (SELECT count(*) FROM documents_issuedartifact WHERE invoice_id = NEW.id) <> 3 THEN
                            RAISE EXCEPTION 'Complete artifacts required for issuance';
                        END IF;
                    END IF;
                    IF NEW.lifecycle_status = 'CANCELLED' AND OLD.lifecycle_status <> 'CANCELLED' THEN
                        IF OLD.lifecycle_status <> 'ISSUED' OR NOT EXISTS (
                            SELECT 1 FROM billing_invoice cancellation
                            WHERE cancellation.original_invoice_id = NEW.id
                              AND cancellation.invoice_type = 'CANCELLATION'
                              AND cancellation.lifecycle_status = 'ISSUED'
                        ) THEN
                            RAISE EXCEPTION 'Issued cancellation required';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """,
            reverse_sql="""CREATE OR REPLACE FUNCTION documents_protect_finalization() RETURNS trigger AS $$
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
                """,
        )
    ]
