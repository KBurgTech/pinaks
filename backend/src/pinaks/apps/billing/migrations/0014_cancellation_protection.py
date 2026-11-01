from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("billing", "0013_remove_invoice_invoice_supported_type_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION billing_protect_issuing_invoice() RETURNS trigger AS $$
                BEGIN
                    IF OLD.lifecycle_status <> 'DRAFT' THEN
                        IF NEW.lifecycle_status NOT IN ('ISSUING', 'ISSUED', 'CANCELLED') OR
                           (OLD.lifecycle_status = 'CANCELLED' AND NEW.lifecycle_status <> 'CANCELLED') OR
                           (to_jsonb(NEW) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version', 'payment_changed_at', 'payment_changed_by_id']) <>
                           (to_jsonb(OLD) - ARRAY['lifecycle_status', 'payment_status', 'modified_at', 'version', 'payment_changed_at', 'payment_changed_by_id']) THEN
                            RAISE EXCEPTION 'Issued invoice content is immutable';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

CREATE FUNCTION billing_protect_cancellation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.invoice_type = 'CANCELLATION' THEN
            RAISE EXCEPTION 'Cancellation evidence is immutable';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.invoice_type = 'CANCELLATION' AND OLD.lifecycle_status = 'DRAFT' THEN
        IF NEW.lifecycle_status NOT IN ('DRAFT', 'ISSUING') OR
           (to_jsonb(NEW) - ARRAY['lifecycle_status', 'invoice_number', 'issuance_key', 'snapshot', 'version', 'modified_at']) <>
           (to_jsonb(OLD) - ARRAY['lifecycle_status', 'invoice_number', 'issuance_key', 'snapshot', 'version', 'modified_at']) THEN
            RAISE EXCEPTION 'Full cancellation content is immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER billing_protect_cancellation_write BEFORE UPDATE OR DELETE ON billing_invoice
FOR EACH ROW EXECUTE FUNCTION billing_protect_cancellation();
CREATE FUNCTION billing_protect_cancellation_line() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM billing_invoice WHERE id = COALESCE(NEW.invoice_id, OLD.invoice_id)
               AND invoice_type = 'CANCELLATION') OR
       (TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM billing_invoice WHERE id = OLD.invoice_id
               AND invoice_type = 'CANCELLATION')) THEN
        RAISE EXCEPTION 'Full cancellation lines are immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER billing_protect_cancellation_line_write BEFORE INSERT OR UPDATE OR DELETE ON billing_invoiceline
FOR EACH ROW EXECUTE FUNCTION billing_protect_cancellation_line();
""",
            reverse_sql="""DROP TRIGGER billing_protect_cancellation_line_write ON billing_invoiceline;
DROP FUNCTION billing_protect_cancellation_line();
DROP TRIGGER billing_protect_cancellation_write ON billing_invoice;
DROP FUNCTION billing_protect_cancellation();

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
        )
    ]
