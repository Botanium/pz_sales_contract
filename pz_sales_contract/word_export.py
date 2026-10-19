"""Read-only Word downloads from the same canonical HTML as contract printing."""
import frappe

from pz_sales_contract.docx_document import contract_docx
from pz_sales_contract.printing import _saved_printable_contract, get_blank_contract_html

DOCX_MIMETYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def _download(html, *, blank=False):
    frappe.local.response.update(type='download',
        filename='petrol-zone-blank-contract.docx' if blank else 'petrol-zone-contract.docx',
        filecontent=contract_docx(html, blank=blank), content_type=DOCX_MIMETYPE,
        display_content_as='attachment')


@frappe.whitelist()
def download_word(name=None):
    if frappe.session.user == 'Guest':
        frappe.throw('Not permitted to download PZ Sales Contracts', frappe.PermissionError)
    if not isinstance(name, str) or not name.strip():
        frappe.throw('Choose a saved PZ Sales Contract to download')
    doc = _saved_printable_contract({'doctype': 'PZ Sales Contract', 'name': name})
    # The enforced template reloads and checks native Read/Print permissions and
    # persisted status. Client-supplied fields and print flags are never accepted.
    html = frappe.render_template('pz_sales_contract/templates/contract.html',
        {'doc': doc})
    _download(html)


@frappe.whitelist()
def download_blank_word(source_contract=None):
    # Reuse the HTML worksheet's source selection, permission checks and whitelist.
    _download(get_blank_contract_html(source_contract), blank=True)
