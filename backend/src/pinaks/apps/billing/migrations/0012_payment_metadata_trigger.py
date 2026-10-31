from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("billing", "0011_invoice_payment_changed_at_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION billing_protect_issuing_invoice() RETURNS trigger AS $$
                BEGIN
                    IF OLD.lifecycle_status <> 'DRAFT' THEN
                        IF NEW.lifecycle_status NOT IN ('ISSUING', 'ISSUED') OR
                           (to_jsonb(NEW) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version', 'payment_changed_at', 'payment_changed_by_id']) <>
                           (to_jsonb(OLD) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version', 'payment_changed_at', 'payment_changed_by_id']) THEN
                            RAISE EXCEPTION 'Issued invoice content is immutable';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
""",
            reverse_sql="""
                CREATE OR REPLACE FUNCTION billing_protect_issuing_invoice() RETURNS trigger AS $$
                BEGIN
                    IF OLD.lifecycle_status <> 'DRAFT' THEN
                        IF NEW.lifecycle_status NOT IN ('ISSUING', 'ISSUED') OR
                           (to_jsonb(NEW) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version']) <>
                           (to_jsonb(OLD) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version']) THEN
                            RAISE EXCEPTION 'Issued invoice content is immutable';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
""",
        )
    ]
