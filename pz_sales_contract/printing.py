import base64
import json
from pathlib import Path

import frappe
from frappe.utils.pdf import pdf_body_html as default_body

from pz_sales_contract.payments import payment_status


def pdf_body_html(template, args, **kwargs):
    if args['doc'].doctype != 'PZ Sales Contract':
        return default_body(template=template, args=args, **kwargs)
    # All native print formats use persisted server data and the mandatory branded
    # template. A forged doc payload or alternate Standard format cannot remove it.
    doc = frappe.get_doc('PZ Sales Contract', args['doc'].name)
    doc.check_permission('read')
    doc.check_permission('print')
    path = Path(frappe.get_app_path('pz_sales_contract'))
    context = dict(doc=doc, state=payment_status(doc),
        clauses=json.loads((path/'terms.json').read_text()),
        logo='data:image/png;base64,'+base64.b64encode((path/'public/petrol_zone_logo.png').read_bytes()).decode(),
        erp_status=['Unsubmitted', 'Submitted', 'Cancelled'][int(doc.docstatus)])
    return frappe.render_template('pz_sales_contract/templates/contract.html', context)
