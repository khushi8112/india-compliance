import frappe


def enqueue_integration_request(**kwargs):
    frappe.enqueue(
        "india_compliance.gst_india.utils.api.create_integration_request",
        **kwargs,
    )


def create_integration_request(
    url=None,
    request_id=None,
    request_headers=None,
    data=None,
    output=None,
    error=None,
    reference_doctype=None,
    reference_name=None,
    update_gstr_action=False,
):
    doc = frappe.get_doc(
        {
            "doctype": "Integration Request",
            "integration_request_service": "India Compliance API",
            "request_id": request_id,
            "url": url,
            "request_headers": pretty_json(request_headers),
            "data": pretty_json(data),
            "output": pretty_json(output),
            "error": pretty_json(error),
            "status": "Failed" if error else "Completed",
            "reference_doctype": reference_doctype,
            "reference_docname": reference_name,
        }
    )
    doc.insert(ignore_permissions=True)

    if update_gstr_action:
        link_integration_request(request_id, doc.name)


def link_integration_request(request_id, doc_name):
    frappe.db.set_value(
        "GSTR Action", {"request_id": request_id}, {"integration_request": doc_name}
    )


def pretty_json(obj):
    if not obj:
        return ""

    if isinstance(obj, str):
        return obj

    return frappe.as_json(obj, indent=4)
