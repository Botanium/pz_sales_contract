import base64
from pathlib import Path

import frappe
from frappe.utils import fmt_money
from frappe.utils.pdf import pdf_body_html as default_body

from pz_sales_contract.contract_terms import clauses_for_contract
from pz_sales_contract.payments import payment_status


def validate_format(doc, method=None):
    if doc.doc_type == 'PZ Sales Contract' and doc.get('print_format_builder_beta'):
        frappe.throw('Beta print builders are unsupported for PZ contracts; use the enforced branded format')
    if doc.doc_type == 'PZ Sales Contract' and 'chrome' in str(doc.get('pdf_generator') or '').lower():
        frappe.throw('Chrome PDF rendering is unsupported for PZ contracts; use native wkhtmltopdf printing')


def guard_renderer():
    """The native beta renderer bypasses pdf_body_html: reject it on HTTP paths."""
    values = frappe.local.form_dict
    canonical = values.get('doctype')
    if isinstance(canonical,str) and canonical.startswith('{'):
        try:
            canonical = frappe.parse_json(canonical)
        except ValueError:
            pass
    doctypes = set(canonical) if isinstance(canonical,dict) else {str(canonical or '')}
    payload = values.get('doc')
    if payload:
        try:
            data = frappe.parse_json(payload) if isinstance(payload,str) else payload
            if isinstance(data,dict):
                doctypes.add(str(data.get('doctype') or ''))
        except (ValueError, TypeError):
            pass
    if 'PZ Sales Contract' in doctypes:
        path = getattr(getattr(frappe.local,'request',None),'path','') or ''
        commands = [str(values.get('cmd') or ''),path]
        weasyprint = any('frappe.utils.weasyprint.' in command or
            'frappe.printing.doctype.print_format.print_format.download_pdf' in command
            for command in commands)
        # API v2 expands its DocType shortcut only after before_request hooks.
        weasyprint = weasyprint or path.rstrip('/') == '/api/v2/method/Print Format/download_pdf'
        if weasyprint or 'chrome' in str(values.get('pdf_generator','')).lower():
            frappe.throw('This renderer bypasses the enforced contract template; use native wkhtmltopdf printing')
        names = [values.get('format'),values.get('print_format')]
        if not any(names):
            names = [frappe.get_meta('PZ Sales Contract').default_print_format or 'Standard']
        for name in filter(None,names):
            settings = frappe.db.get_value('Print Format',name,
                ['print_format_builder_beta','pdf_generator'],as_dict=True)
            if settings and settings.print_format_builder_beta:
                frappe.throw('Beta print builders are unsupported for PZ contracts; use the enforced branded format')
            if settings and 'chrome' in str(settings.pdf_generator or '').lower():
                frappe.throw('Chrome PDF rendering is unsupported for PZ contracts; use native wkhtmltopdf printing')


def pdf_body_html(template, args, **kwargs):
    if args['doc'].doctype != 'PZ Sales Contract':
        return default_body(template=template, args=args, **kwargs)
    # All native print formats use persisted server data and the mandatory branded
    # template. A forged doc payload or alternate Standard format cannot remove it.
    doc = frappe.get_doc('PZ Sales Contract', args['doc'].name)
    doc.check_permission('read')
    doc.check_permission('print')
    path = Path(frappe.get_app_path('pz_sales_contract'))
    holiday_data = frappe.parse_json(doc.holiday_calendar_snapshot) if doc.holiday_calendar_snapshot else {
        'name': '', 'from_date': '', 'to_date': '', 'holidays': [],
    }
    holiday = frappe._dict(holiday_data)
    holiday.holidays = [frappe._dict(row) for row in holiday.get('holidays', [])]
    specification_rows = {}
    for row in doc.specifications:
        specification_rows.setdefault(row.item_code, []).append(row)
    spec_items = []
    seen = set()
    for row in doc.items:
        key = (row.item_code,row.grade)
        if key not in seen:
            seen.add(key)
            spec_items.append({
                'item_code': row.item_code,
                'item_name': row.item_name,
                'grade': row.grade,
                'specification_rows': specification_rows.get(row.item_code, []),
            })
    context = dict(doc=doc, state=payment_status(doc), holiday=holiday, spec_items=spec_items,
        format_money=fmt_money,
        clauses=clauses_for_contract(doc),
        logo='data:image/png;base64,'+base64.b64encode((path/'public/petrol_zone_logo.png').read_bytes()).decode(),
        erp_status=['Unsubmitted', 'Submitted', 'Cancelled'][int(doc.docstatus)])
    return frappe.render_template('pz_sales_contract/templates/contract.html', context)


def pdf_header_html(soup, head, content, styles, html_id, css):
    from frappe.utils.pdf import pdf_header_html as native
    if not content.find(class_='pz-running') and not content.find(class_='pz-footer'):
        return native(soup,head,content,styles,html_id,css)
    # Frappe's generic wrapper adds body/print margins that clip a compact running
    # header. Use a minimal wrapper for our own identified header/footer only.
    return '<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:0;font-family:Arial,sans-serif;font-size:8pt;color:#555}.pz-running,.pz-footer{border-bottom:1px solid #efa90a;padding:3px 0}strong{color:#815200}</style></head><body>'+str(content)+'</body></html>'
