"""Narrow request-method bridge for the existing Signal Desk Server Script."""
import frappe


@frappe.whitelist(methods=["GET"])
def is_get_request():
    """Return a boolean only; never expose request metadata or ERP records.

    Check the actual request here because safe-exec omits request.method and
    skips whitelisted method verb validation during frappe.call.
    """
    if frappe.session.user != "pz.signal.desk@petrolzone.local":
        frappe.throw("Not permitted", frappe.PermissionError)
    request = getattr(frappe.local, "request", None)
    return bool(request and request.method == "GET")
