# Direct party entry

New contract families use `party_entry_version = direct-v1`. Company and Customer remain required ERP identities for accounting, orders, access controls and first-customer/payment history. The printed parties are user-entered fields; no Address or Contact selection is required. Their historical Link columns remain stored and hidden, with no destructive migration.

Seller legal name, address, email and phone start with the user-supplied Petrol Zone values and remain editable. Existing seller signatory/name and position requirements remain. Buyer legal name, address, primary phone, representative name and signatory position are required. Registration/tax/ID and the second email/phone field are optional; empty values are omitted from print. The existing buyer_position field sits immediately after the buyer representative in Buyer Details. The optional combined email/phone field accepts phone-only text and has no email-only validator. Buyer example values are never defaults.

The server enforces nonblank party text and discards Contact/Address payload links for new-policy records. Party values print from the saved contract, escaped as text. Customer or Company master edits do not overwrite saved contract party text. Switching Customer on an unsaved form clears buyer details so the previous buyer is not carried forward.

Existing contracts and their amendments retain their policy and stored snapshots without new mandatory requirements or automatic seller defaults. Historical hidden Address/Contact links are immutable on saves and amendments; users edit party text instead. Their original print presentation remains unless new party fields are explicitly populated; edits to existing party text are retained. No bulk data rewrite is performed. New-policy amendments keep their source policy and party text.

Native Sales Orders retain Customer/Company identity and their own native address/contact behavior, independently of direct contract party text. New-policy contracts do not forward or compare Address/Contact links to the Sales Order. Historical orders retain their existing association checks. Contract prices, payment evidence, Grade, packaging, USD and delivery/tax policies are unchanged.

Validation includes local schema, mandatory-field and form behavior checks plus native save, print, amendment and Sales Order tests in the disposable CI bench. No production installation, migration or transaction is authorized by this code change.


Payment instructions are optional: nominated bank, agreed cash account, beneficiary, bank/branch, currency/account/IBAN and SWIFT/reference can all remain empty. Blank rows and an empty payment table are omitted from print. The nominated bank field is Data, retaining previous account-name text without rewriting stored values; the optional cash field remains an ERP Account Link. Desk may suggest configured payment details, but the server does not refill cleared payment inputs. Native receipt matching still requires exact account identity and the existing allocation, currency, ledger and reconciliation evidence. Blank or unrecognized bank text cannot confirm an advance.

An omitted, null or empty Discount normalizes to zero before native arithmetic. Negative, nonnumeric, nonfinite or excessive discounts are rejected. Saving a draft never creates or submits a Sales Order.
