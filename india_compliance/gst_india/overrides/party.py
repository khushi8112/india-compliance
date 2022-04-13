import json

import frappe
from frappe import _, bold

from india_compliance.gst_india.utils import (
    is_valid_pan,
    validate_gst_category,
    validate_gstin,
)


def validate_party(doc, method=None):
    doc.gstin = validate_gstin(doc.gstin)
    validate_gst_category(doc.gst_category, doc.gstin)
    validate_pan(doc)
    set_docs_with_previous_gstin(doc)


def validate_pan(doc):
    """
    - Set PAN from GSTIN if available.
    - Validate PAN.
    """

    if doc.gstin:
        doc.pan = (
            pan_from_gstin if is_valid_pan(pan_from_gstin := doc.gstin[2:12]) else ""
        )
        return

    if not doc.pan:
        return

    doc.pan = doc.pan.upper().strip()
    if not is_valid_pan(doc.pan):
        frappe.throw(_("Invalid PAN format"))


def set_docs_with_previous_gstin(doc, method=True):
    if not frappe.request or frappe.flags.in_update_docs_with_previous_gstin:
        return

    previous_gstin = (doc.get_doc_before_save() or {}).get("gstin")
    if not previous_gstin or previous_gstin == doc.gstin:
        return

    docs_with_previous_gstin = get_docs_with_previous_gstin(
        previous_gstin, doc.doctype, doc.name
    )
    if not docs_with_previous_gstin:
        return

    frappe.response.docs_with_previous_gstin = docs_with_previous_gstin
    frappe.response.previous_gstin = previous_gstin


def get_docs_with_previous_gstin(gstin, doctype, docname):
    docs_with_previous_gstin = {}
    for dt in ("Address", "Supplier", "Customer", "Company"):
        for doc in frappe.get_all(dt, filters={"gstin": gstin}):
            if doc.name == docname and doctype == dt:
                continue

            docs_with_previous_gstin.setdefault(dt, []).append(doc.name)

    return docs_with_previous_gstin


@frappe.whitelist()
def update_docs_with_previous_gstin(gstin, gst_category, docs_with_previous_gstin):
    frappe.flags.in_update_docs_with_previous_gstin = True
    docs_with_previous_gstin = json.loads(docs_with_previous_gstin)
    ignored_docs = {}

    for doctype, docnames in docs_with_previous_gstin.items():
        for docname in docnames:
            try:
                doc = frappe.get_doc(doctype, docname)
                doc.gstin = gstin
                doc.gst_category = gst_category
                doc.save()
            except frappe.PermissionError:
                frappe.clear_last_message()
                ignored_docs.setdefault(doctype, []).append(docname)
            except Exception as e:
                # TODO: handle this in better way
                frappe.clear_last_message()
                frappe.throw(
                    "Error updating {0} {1}:<br/> {2}".format(doctype, docname, str(e))
                )

    if not ignored_docs:
        return frappe.msgprint(
            _("Updated GSTIN in all documents"), indicator="green", alert=True
        )

    message = _(
        "Following documents could not be updated due to insufficient"
        " permission:<br/><br/>"
    )

    for doctype, docnames in ignored_docs.items():
        if not docnames:
            continue

        message += f"{bold(doctype)}:<br/>{'<br/>'.join(docnames)}"

    frappe.msgprint(message, title=_("Insufficient Permission"), indicator="yellow")


# modified version of erpnext.selling.doctype.customer.customer.create_primary_address
def create_primary_address(doc, method=None):
    if not doc.is_new() or not doc.get("_address_line1"):
        return

    from frappe.contacts.doctype.address.address import get_address_display

    address = make_address(doc)
    address_display = get_address_display(address.as_dict())

    doc.db_set(f"{doc.doctype.lower()}_primary_address", address.name)
    doc.db_set("primary_address", address_display)


def make_address(doc):
    required_fields = []
    for field in ("city", "country"):
        if not doc.get(field):
            required_fields.append(f"<li>{_(doc.meta.get_label(field))}</li>")

    if required_fields:
        frappe.throw(
            "{0} <br><br> <ul>{1}</ul>".format(
                _("Following fields are mandatory to create Address:"),
                "\n".join(required_fields),
            ),
            frappe.MandatoryError,
            title=_("Missing Required Values"),
        )

    return frappe.get_doc(
        {
            "doctype": "Address",
            "address_title": doc.name,
            "address_line1": doc.get("_address_line1"),
            "address_line2": doc.get("address_line2"),
            "city": doc.get("city"),
            "state": doc.get("state"),
            "pincode": doc.get("pincode"),
            "country": doc.get("country"),
            "gstin": doc.gstin,
            "gst_category": doc.gst_category,
            "links": [{"link_doctype": doc.doctype, "link_name": doc.name}],
        }
    ).insert()
