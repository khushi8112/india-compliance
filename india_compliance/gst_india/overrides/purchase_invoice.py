import frappe
from frappe import _
from frappe.utils import flt

from india_compliance.gst_india.overrides.sales_invoice import (
    update_dashboard_with_gst_logs,
)
from india_compliance.gst_india.overrides.transaction import (
    validate_hsn_codes as _validate_hsn_codes,
)
from india_compliance.gst_india.overrides.transaction import (
    validate_transaction,
)
from india_compliance.gst_india.utils import is_api_enabled, validate_invoice_number
from india_compliance.gst_india.utils.e_waybill import get_e_waybill_info


def onload(doc, method=None):
    if doc.docstatus != 1:
        return

    if doc.gst_category == "Overseas":
        doc.set_onload(
            "bill_of_entry_exists",
            frappe.db.exists(
                "Bill of Entry",
                {"purchase_invoice": doc.name, "docstatus": 1},
            ),
        )

    if not doc.get("ewaybill"):
        return

    gst_settings = frappe.get_cached_doc("GST Settings")

    if not is_api_enabled(gst_settings):
        return

    if (
        gst_settings.enable_e_waybill
        and gst_settings.enable_e_waybill_from_pi
        and doc.ewaybill
    ):
        doc.set_onload("e_waybill_info", get_e_waybill_info(doc))


def validate(doc, method=None):
    if validate_transaction(doc) is False:
        return

    validate_hsn_codes(doc)
    if doc.is_reverse_charge and not doc.supplier_gstin:
        validate_invoice_number(doc)

    set_ineligibility_reason(doc)
    update_itc_totals(doc)
    validate_supplier_invoice_number(doc)
    validate_with_inward_supply(doc)
    set_reconciliation_status(doc)


def on_cancel(doc, method=None):
    frappe.db.set_value(
        "GST Inward Supply",
        {"link_doctype": "Purchase Invoice", "link_name": doc.name},
        {
            "match_status": "",
            "link_name": "",
            "link_doctype": "",
            "action": "No Action",
        },
    )


def set_reconciliation_status(doc):
    reconciliation_status = "Not Applicable"

    if is_b2b_invoice(doc):
        reconciliation_status = "Unreconciled"

    doc.reconciliation_status = reconciliation_status


def is_b2b_invoice(doc):
    return not (
        doc.supplier_gstin in ["", None]
        or doc.gst_category in ["Registered Composition", "Unregistered", "Overseas"]
        or doc.supplier_gstin == doc.company_gstin
        or doc.is_opening == "Yes"
    )


def update_itc_totals(doc, method=None):
    # Set default value
    set_itc_classification(doc)
    validate_reverse_charge(doc)

    # Initialize values
    doc.itc_integrated_tax = 0
    doc.itc_state_tax = 0
    doc.itc_central_tax = 0
    doc.itc_cess_amount = 0

    if doc.ineligibility_reason == "ITC restricted due to PoS rules":
        return

    for tax in doc.get("taxes"):
        if tax.gst_tax_type == "igst":
            doc.itc_integrated_tax += flt(tax.base_tax_amount_after_discount_amount)

        if tax.gst_tax_type == "sgst":
            doc.itc_state_tax += flt(tax.base_tax_amount_after_discount_amount)

        if tax.gst_tax_type == "cgst":
            doc.itc_central_tax += flt(tax.base_tax_amount_after_discount_amount)

        if tax.gst_tax_type == "cess":
            doc.itc_cess_amount += flt(tax.base_tax_amount_after_discount_amount)


def set_itc_classification(doc):
    if doc.gst_category == "Overseas":
        for item in doc.items:
            if not item.gst_hsn_code.startswith("99"):
                doc.itc_classification = "Import Of Goods"
                break
        else:
            doc.itc_classification = "Import Of Service"

    elif doc.is_reverse_charge:
        doc.itc_classification = "ITC on Reverse Charge"

    elif doc.gst_category == "Input Service Distributor" and doc.is_internal_transfer():
        doc.itc_classification = "Input Service Distributor"

    else:
        doc.itc_classification = "All Other ITC"


def validate_supplier_invoice_number(doc):
    if (
        doc.bill_no
        or doc.gst_category == "Unregistered"
        or not frappe.get_cached_value(
            "GST Settings", "GST Settings", "require_supplier_invoice_no"
        )
    ):
        return

    frappe.throw(
        _("As per your GST Settings, Bill No is mandatory for Purchase Invoice."),
        title=_("Missing Mandatory Field"),
    )


def get_dashboard_data(data):
    transactions = data.setdefault("transactions", [])
    reference_section = next(
        (row for row in transactions if row.get("label") == "Reference"), None
    )

    if reference_section is None:
        reference_section = {"label": "Reference", "items": []}
        transactions.append(reference_section)

    reference_section["items"].append("Bill of Entry")

    update_dashboard_with_gst_logs(
        "Purchase Invoice",
        data,
        "e-Waybill Log",
        "e-Invoice Log",
        "Integration Request",
        "GST Inward Supply",
    )

    return data


def validate_with_inward_supply(doc):
    if not doc.get("_inward_supply"):
        return

    mismatch_fields = {}
    for field in [
        "company",
        "company_gstin",
        "supplier_gstin",
        "bill_no",
        "bill_date",
        "is_reverse_charge",
        "place_of_supply",
    ]:
        if doc.get(field) != doc._inward_supply.get(field):
            mismatch_fields[field] = doc._inward_supply.get(field)

    # mismatch for taxable_value
    taxable_value = sum([item.taxable_value for item in doc.items])
    if taxable_value != doc._inward_supply.get("taxable_value"):
        mismatch_fields["Taxable Value"] = doc._inward_supply.get("taxable_value")

    # mismatch for taxes
    for tax in ["cgst", "sgst", "igst", "cess"]:
        tax_amount = get_tax_amount(doc.taxes, tax)
        if tax == "cess":
            tax_amount += get_tax_amount(doc.taxes, "cess_non_advol")

        if tax_amount == doc._inward_supply.get(tax):
            continue

        mismatch_fields[tax.upper()] = doc._inward_supply.get(tax)

    if mismatch_fields:
        message = (
            "Purchase Invoice does not match with releted GST Inward Supply.<br>"
            "Following values are not matching from 2A/2B: <br>"
        )
        for field, value in mismatch_fields.items():
            message += f"<br>{field}: {value}"

        frappe.msgprint(
            _(message),
            title=_("Mismatch with GST Inward Supply"),
        )

    elif doc._action == "submit":
        frappe.msgprint(
            _("Invoice matched with GST Inward Supply"),
            alert=True,
            indicator="green",
        )


def get_tax_amount(taxes, gst_tax_type):
    if not (taxes or gst_tax_type):
        return 0

    return sum(
        [
            tax.base_tax_amount_after_discount_amount
            for tax in taxes
            if tax.gst_tax_type == gst_tax_type
        ]
    )


def set_ineligibility_reason(doc, show_alert=True):
    doc.ineligibility_reason = ""

    for item in doc.items:
        if item.is_ineligible_for_itc:
            doc.ineligibility_reason = "Ineligible As Per Section 17(5)"
            break

    if (
        doc.place_of_supply not in ["96-Other Countries", "97-Other Territory"]
        and doc.place_of_supply[:2] != doc.company_gstin[:2]
    ):
        doc.ineligibility_reason = "ITC restricted due to PoS rules"

    if show_alert and doc.ineligibility_reason:
        frappe.msgprint(
            _("ITC Ineligible: {0}").format(frappe.bold(doc.ineligibility_reason)),
            alert=True,
            indicator="orange",
        )


def validate_reverse_charge(doc):
    if doc.itc_classification != "Import Of Goods" or not doc.is_reverse_charge:
        return

    frappe.throw(_("Reverse Charge is not applicable on Import of Goods"))


def validate_hsn_codes(doc):
    # To determine whether BOE is applicable or not.
    if doc.gst_category != "Overseas":
        return

    _validate_hsn_codes(
        doc,
        throw=True,
        message="GST HSN Code is mandatory for Overseas Purchase Invoice.<br>",
    )
