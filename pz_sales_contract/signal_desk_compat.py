"""Narrow request-method bridge for the fixed Signal Desk integration identity."""

import frappe

EXPECTED_USER = "pz.signal.desk@petrolzone.local"


@frappe.whitelist(allow_guest=False, methods=["GET"])
def is_get_request():
    depth = getattr(frappe.flags, "in_safe_exec", 0)
    if frappe.session.user != EXPECTED_USER or not isinstance(depth, int) or depth <= 0:
        raise frappe.PermissionError("Not permitted")
    try:
        request = getattr(frappe.local, "request", None)
        return getattr(request, "method", None) == "GET"
    except RuntimeError:
        return False
