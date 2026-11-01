from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("billing", "0017_remove_invoice_invoice_supported_type_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""
CREATE OR REPLACE FUNCTION billing_validate_credit_reservation() RETURNS trigger AS $$
DECLARE original billing_invoice; allocation jsonb; credited billing_invoiceline;
        source billing_invoiceline; prior_qty numeric; prior_net numeric;
        prior_tax numeric; prior_gross numeric; selected_count integer;
BEGIN
    IF NEW.invoice_type = 'REPLACEMENT' THEN RETURN NEW; END IF;
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

CREATE FUNCTION billing_validate_replacement() RETURNS trigger AS $$
DECLARE original billing_invoice;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.invoice_type = 'REPLACEMENT' THEN RAISE EXCEPTION 'Replacement identity is permanent'; END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.invoice_type = 'REPLACEMENT' THEN
        IF (NEW.invoice_type, NEW.original_invoice_id, NEW.correction_reason, NEW.correction_key) IS DISTINCT FROM
           (OLD.invoice_type, OLD.original_invoice_id, OLD.correction_reason, OLD.correction_key) THEN
            RAISE EXCEPTION 'Replacement identity is immutable';
        END IF;
    END IF;
    IF NEW.invoice_type = 'REPLACEMENT' THEN
        SELECT * INTO original FROM billing_invoice WHERE id = NEW.original_invoice_id FOR UPDATE;
        IF original.id IS NULL OR original.invoice_type <> 'STANDARD' OR original.lifecycle_status <> 'CANCELLED' OR
           NOT EXISTS (SELECT 1 FROM billing_invoice WHERE original_invoice_id = original.id AND invoice_type = 'CANCELLATION' AND lifecycle_status = 'ISSUED') OR
           NEW.credit_allocations <> '[]'::jsonb OR NEW.issue_date < original.issue_date THEN
            RAISE EXCEPTION 'Replacement requires completed full cancellation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER billing_validate_replacement_write BEFORE INSERT OR UPDATE OR DELETE ON billing_invoice
FOR EACH ROW EXECUTE FUNCTION billing_validate_replacement();
""",
            reverse_sql="""
DROP TRIGGER billing_validate_replacement_write ON billing_invoice; DROP FUNCTION billing_validate_replacement();
CREATE OR REPLACE FUNCTION billing_validate_credit_reservation() RETURNS trigger AS $$
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
""",
        )
    ]
