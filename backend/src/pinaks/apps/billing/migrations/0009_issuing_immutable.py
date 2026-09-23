from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("billing", "0008_remove_invoice_invoice_supported_lifecycle_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION billing_protect_issuing_invoice() RETURNS trigger AS $$
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
                CREATE TRIGGER billing_protect_issuing_invoice_update
                    BEFORE UPDATE ON billing_invoice
                    FOR EACH ROW EXECUTE FUNCTION billing_protect_issuing_invoice();

                CREATE FUNCTION billing_protect_issuing_line() RETURNS trigger AS $$
                DECLARE parent_status text;
                BEGIN
                    SELECT lifecycle_status INTO parent_status FROM billing_invoice
                    WHERE id = COALESCE(OLD.invoice_id, NEW.invoice_id);
                    IF parent_status <> 'DRAFT' THEN
                        RAISE EXCEPTION 'Issued invoice lines are immutable';
                    END IF;
                    IF TG_OP = 'UPDATE' AND NEW.invoice_id <> OLD.invoice_id THEN
                        SELECT lifecycle_status INTO parent_status FROM billing_invoice WHERE id = NEW.invoice_id;
                        IF parent_status <> 'DRAFT' THEN
                            RAISE EXCEPTION 'Issued invoice lines are immutable';
                        END IF;
                    END IF;
                    RETURN COALESCE(NEW, OLD);
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER billing_protect_issuing_line_write
                    BEFORE INSERT OR UPDATE OR DELETE ON billing_invoiceline
                    FOR EACH ROW EXECUTE FUNCTION billing_protect_issuing_line();
            """,
            reverse_sql="""
                DROP TRIGGER billing_protect_issuing_line_write ON billing_invoiceline;
                DROP FUNCTION billing_protect_issuing_line();
                DROP TRIGGER billing_protect_issuing_invoice_update ON billing_invoice;
                DROP FUNCTION billing_protect_issuing_invoice();
            """,
        ),
    ]
