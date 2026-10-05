# Direct party entry

New contract families use `party_entry_version = direct-v1`. Company and Customer remain required ERP identities for accounting, orders, access controls and first-customer/payment history. The printed parties are user-entered fields; no Address or Contact selection is required. Their historical Link columns remain stored and hidden, with no destructive migration.

Seller legal name, address, email and phone start with the user-supplied Petrol Zone values and remain editable. Existing seller signatory/name and position requirements remain. Buyer legal name, registration/tax/ID, address, phone, representative name, signatory position and email/phone are required. The existing buyer_position field sits immediately after the buyer representative in Buyer Details. The combined email/phone field accepts phone-only text and has no email-only validator. Buyer example values are never defaults.

The server enforces nonblank party text and discards Contact/Address payload links for new-policy records. Party values print from the saved contract, escaped as text. Customer or Company master edits do not overwrite saved contract party text. Switching Customer on an unsaved form clears buyer details so the previous buyer is not carried forward.

Existing contracts and their amendments retain their policy and stored snapshots without new mandatory requirements or automatic seller defaults. Their original print presentation remains unless new party fields are explicitly populated; edits to existing party text are retained. No bulk data rewrite is performed. New-policy amendments keep their source policy and party text.

Native Sales Orders retain Customer/Company identity and their own native address/contact behavior, independently of direct contract party text. New-policy contracts do not forward or compare Address/Contact links to the Sales Order. Historical orders retain their existing association checks. Contract prices, payment evidence, Grade, packaging, USD and delivery/tax policies are unchanged.

Validation includes local schema, mandatory-field and form behavior checks plus native save, print, amendment and Sales Order tests in the disposable CI bench. No production installation, migration or transaction is authorized by this code change.
