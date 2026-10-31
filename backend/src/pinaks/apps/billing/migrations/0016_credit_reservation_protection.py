from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("billing", "0015_remove_invoice_invoice_supported_type_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""CREATE OR REPLACE FUNCTION billing_protect_cancellation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.invoice_type IN ('CANCELLATION', 'CREDIT_NOTE') THEN
            RAISE EXCEPTION 'Cancellation evidence is immutable';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.invoice_type IN ('CANCELLATION', 'CREDIT_NOTE') AND OLD.lifecycle_status = 'DRAFT' THEN
        IF NEW.lifecycle_status NOT IN ('DRAFT', 'ISSUING') OR
           (to_jsonb(NEW) - ARRAY['lifecycle_status', 'invoice_number', 'issuance_key', 'snapshot', 'version', 'modified_at']) <>
           (to_jsonb(OLD) - ARRAY['lifecycle_status', 'invoice_number', 'issuance_key', 'snapshot', 'version', 'modified_at']) THEN
            RAISE EXCEPTION 'Full cancellation content is immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION billing_protect_cancellation_line() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM billing_invoice WHERE id = COALESCE(NEW.invoice_id, OLD.invoice_id)
               AND invoice_type IN ('CANCELLATION', 'CREDIT_NOTE')) OR
       (TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM billing_invoice WHERE id = OLD.invoice_id
               AND invoice_type IN ('CANCELLATION', 'CREDIT_NOTE'))) THEN
        RAISE EXCEPTION 'Full cancellation lines are immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;


CREATE FUNCTION billing_validate_credit_reservation() RETURNS trigger AS $$
DECLARE original billing_invoice; allocation jsonb; credited billing_invoiceline;
        source billing_invoiceline; prior_qty numeric; prior_net numeric;
        prior_tax numeric; prior_gross numeric; selected_count integer;
BEGIN
    IF NEW.invoice_type = 'STANDARD' THEN
        IF NEW.credit_allocations <> '[]'::jsonb THEN
            RAISE EXCEPTION 'Standard invoices cannot reserve credits';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.invoice_type <> 'STANDARD' THEN RETURN NEW; END IF;
    END IF;
    SELECT * INTO original FROM billing_invoice WHERE id = NEW.original_invoice_id FOR UPDATE;
    IF original.invoice_type <> 'STANDARD' OR original.lifecycle_status <> 'ISSUED' THEN
        RAISE EXCEPTION 'Credits require an issued standard original';
    END IF;
    IF EXISTS (SELECT 1 FROM billing_invoice WHERE original_invoice_id = original.id
               AND id <> NEW.id AND (invoice_type = 'CANCELLATION' OR NEW.invoice_type = 'CANCELLATION')) THEN
        RAISE EXCEPTION 'Full cancellation and partial credits are mutually exclusive';
    END IF;
    IF NEW.invoice_type = 'CANCELLATION' THEN RETURN NEW; END IF;
    selected_count := jsonb_array_length(NEW.credit_allocations);
    IF selected_count < 1 OR selected_count > 200 OR selected_count <>
       (SELECT count(*) FROM billing_invoiceline WHERE invoice_id = NEW.id) OR
       selected_count <> (SELECT count(DISTINCT value->>'position') FROM jsonb_array_elements(NEW.credit_allocations)) THEN
        RAISE EXCEPTION 'Invalid credit allocations';
    END IF;
    FOR allocation IN SELECT value FROM jsonb_array_elements(NEW.credit_allocations) LOOP
        SELECT * INTO source FROM billing_invoiceline WHERE invoice_id = original.id AND position = (allocation->>'position')::int;
        SELECT l.* INTO credited FROM jsonb_array_elements(NEW.credit_allocations) WITH ORDINALITY a(value, n)
            JOIN billing_invoiceline l ON l.invoice_id = NEW.id AND l.position = a.n
            WHERE a.value = allocation;
        IF source.id IS NULL OR credited.id IS NULL OR
           credited.quantity <> (allocation->>'quantity')::numeric OR
           credited.unit_price <> (allocation->>'unit_price')::numeric OR
           credited.unit_price > source.unit_price OR
           (to_jsonb(credited) - ARRAY['id','invoice_id','position','quantity','unit_price','net_total','tax_total','gross_total']) <>
           (to_jsonb(source) - ARRAY['id','invoice_id','position','quantity','unit_price','net_total','tax_total','gross_total']) THEN
            RAISE EXCEPTION 'Credit must copy original line semantics';
        END IF;
        SELECT COALESCE(sum(l.quantity),0), COALESCE(sum(l.net_total),0),
               COALESCE(sum(l.tax_total),0), COALESCE(sum(l.gross_total),0)
        INTO prior_qty, prior_net, prior_tax, prior_gross
        FROM billing_invoice i
        CROSS JOIN LATERAL jsonb_array_elements(i.credit_allocations) WITH ORDINALITY a(value,n)
        JOIN billing_invoiceline l ON l.invoice_id = i.id AND l.position = a.n
        WHERE i.original_invoice_id = original.id AND i.invoice_type = 'CREDIT_NOTE'
              AND i.id <> NEW.id AND (a.value->>'position')::int = source.position;
        IF prior_qty + credited.quantity > source.quantity OR
           prior_net + credited.net_total > source.net_total OR
           prior_tax + credited.tax_total > source.tax_total OR
           prior_gross + credited.gross_total > source.gross_total THEN
            RAISE EXCEPTION 'Cumulative credit exceeds original line';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER billing_validate_credit_reservation_write BEFORE INSERT OR UPDATE ON billing_invoice
FOR EACH ROW EXECUTE FUNCTION billing_validate_credit_reservation();
""",
            reverse_sql="""DROP TRIGGER billing_validate_credit_reservation_write ON billing_invoice; DROP FUNCTION billing_validate_credit_reservation();
CREATE OR REPLACE FUNCTION billing_protect_cancellation() RETURNS trigger AS $$
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

CREATE OR REPLACE FUNCTION billing_protect_cancellation_line() RETURNS trigger AS $$
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

""",
        )
    ]
