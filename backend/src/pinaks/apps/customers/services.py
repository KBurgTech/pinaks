from collections.abc import Mapping, Sequence

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.custom_fields.services import validate_custom_data
from pinaks.apps.customers.models import BillingRecipient, Customer, CustomerAddress

_CUSTOMER_FIELDS = (
    "customer_number",
    "party_type",
    "given_name",
    "family_name",
    "organization_name",
    "email",
    "phone",
    "preferred_language",
)
_RECIPIENT_FIELDS = (
    "party_type",
    "given_name",
    "family_name",
    "organization_name",
    "email",
    "phone",
    "address_line_1",
    "address_line_2",
    "postal_code",
    "city",
    "country_code",
)


def recipient_snapshot(
    *,
    source: str,
    customer: Customer,
    recipient_id: int | None = None,
    source_customer_id: int | None = None,
    values: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Copy current recipient data into a draft without a mutable source link."""
    if source in ("customer", "known_customer"):
        selected = customer if source == "customer" else Customer.objects.get(pk=source_customer_id)
        address = selected.addresses.filter(is_primary=True).first()
        if address is None:
            raise ValidationError({"recipient": "The selected customer needs a primary address."})
        data = {field: str(getattr(selected, field)) for field in _RECIPIENT_FIELDS[:6]}
        data.update({field: str(getattr(address, field)) for field in _RECIPIENT_FIELDS[6:]})
    elif source == "saved":
        selected_recipient = BillingRecipient.objects.get(pk=recipient_id, customer=customer)
        data = {field: str(getattr(selected_recipient, field)) for field in _RECIPIENT_FIELDS}
    elif source == "manual" and values is not None:
        if set(values) - set(_RECIPIENT_FIELDS):
            raise ValidationError({"recipient": "Unsupported recipient field."})
        candidate = BillingRecipient(customer=customer, **values)
        candidate.full_clean(exclude=("customer",))
        data = {field: str(getattr(candidate, field)) for field in _RECIPIENT_FIELDS}
    else:
        raise ValidationError({"recipient": "Unsupported recipient source."})
    return data


class CustomerNumberImmutableError(ValueError):
    pass


def _replace_addresses(customer: Customer, raw_addresses: object) -> None:
    if not isinstance(raw_addresses, Sequence) or isinstance(raw_addresses, (str, bytes)):
        raise ValidationError({"addresses": "Addresses must be a list."})
    if not raw_addresses:
        raise ValidationError({"addresses": "At least one address is required."})
    addresses: list[CustomerAddress] = []
    for raw_address in raw_addresses:
        if not isinstance(raw_address, Mapping):
            raise ValidationError({"addresses": "Each address must be an object."})
        address = CustomerAddress(customer=customer, **dict(raw_address))
        address.full_clean(validate_constraints=False)
        addresses.append(address)
    labels = [address.label for address in addresses]
    if len(labels) != len(set(labels)):
        raise ValidationError({"addresses": "Address labels must be unique per customer."})
    if sum(address.is_primary for address in addresses) != 1:
        raise ValidationError({"addresses": "Exactly one address must be primary."})
    customer.addresses.all().delete()
    CustomerAddress.objects.bulk_create(addresses)


@transaction.atomic
def create_customer(*, values: Mapping[str, object], actor: User, correlation_id: str) -> Customer:
    customer = Customer()
    for field in _CUSTOMER_FIELDS:
        if field in values:
            setattr(customer, field, values[field])
    customer.custom_data = validate_custom_data(
        target="customer", values=values.get("custom_data", {}), existing=customer.custom_data
    )
    customer.full_clean()
    customer.save(force_insert=True)
    _replace_addresses(customer, values.get("addresses", []))
    record_event(
        actor=actor,
        action_code="customers.customer_created",
        target_type="customers.customer",
        target_identifier=str(customer.pk),
        correlation_id=correlation_id,
        metadata={
            "changed_fields": sorted(values),
            "party_type": customer.party_type,
        },
    )
    return customer


@transaction.atomic
def update_customer(
    *, customer: Customer, values: Mapping[str, object], actor: User, correlation_id: str
) -> Customer:
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if "customer_number" in values and values["customer_number"] != customer.customer_number:
        raise CustomerNumberImmutableError("The customer number cannot be changed.")
    for field in _CUSTOMER_FIELDS:
        if field in values:
            setattr(customer, field, values[field])
    customer.custom_data = validate_custom_data(
        target="customer", values=values.get("custom_data", {}), existing=customer.custom_data
    )
    customer.full_clean()
    customer.save()
    if "addresses" in values:
        _replace_addresses(customer, values["addresses"])
    record_event(
        actor=actor,
        action_code="customers.customer_updated",
        target_type="customers.customer",
        target_identifier=str(customer.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values)},
    )
    return customer


@transaction.atomic
def archive_customer(*, customer: Customer, actor: User, correlation_id: str) -> Customer:
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if not customer.is_archived:
        customer.is_archived = True
        customer.save(update_fields=("is_archived", "modified_at"))
        record_event(
            actor=actor,
            action_code="customers.customer_archived",
            target_type="customers.customer",
            target_identifier=str(customer.pk),
            correlation_id=correlation_id,
        )
    return customer


def search_customers(*, search: str = "", archived: bool = False) -> QuerySet[Customer]:
    customers = Customer.objects.filter(is_archived=archived).prefetch_related("addresses")
    if search:
        customers = customers.filter(
            Q(customer_number__icontains=search)
            | Q(given_name__icontains=search)
            | Q(family_name__icontains=search)
            | Q(organization_name__icontains=search)
            | Q(email__icontains=search)
        )
    return customers.order_by("customer_number")


@transaction.atomic
def create_billing_recipient(
    *, customer: Customer, values: Mapping[str, object], actor: User, correlation_id: str
) -> BillingRecipient:
    recipient = BillingRecipient(customer=customer)
    for field in _RECIPIENT_FIELDS:
        if field in values:
            setattr(recipient, field, values[field])
    recipient.save(force_insert=True)
    record_event(
        actor=actor,
        action_code="customers.billing_recipient_created",
        target_type="customers.billing_recipient",
        target_identifier=str(recipient.pk),
        correlation_id=correlation_id,
        metadata={"customer_id": customer.pk, "party_type": recipient.party_type},
    )
    return recipient


@transaction.atomic
def update_billing_recipient(
    *, recipient: BillingRecipient, values: Mapping[str, object], actor: User, correlation_id: str
) -> BillingRecipient:
    recipient = BillingRecipient.objects.select_for_update().get(pk=recipient.pk)
    for field in _RECIPIENT_FIELDS:
        if field in values:
            setattr(recipient, field, values[field])
    recipient.save()
    record_event(
        actor=actor,
        action_code="customers.billing_recipient_updated",
        target_type="customers.billing_recipient",
        target_identifier=str(recipient.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values), "customer_id": recipient.customer_id},
    )
    return recipient
