# Product descriptions and blank printing

Each Products and Price row has an optional **Description** (plain, multiline text) next to the Item name. Expand a row to edit it. It is saved and printed with that product. The Item lookup no longer supplies or replaces this wording; changing or clearing an Item retains the description so the user can review it deliberately. Existing saved descriptions, including those previously copied from Item masters, are retained. Blank descriptions stay blank. Submitted contracts retain native read-only protection; amendments copy the recorded description.

HTML-like descriptions use Frappe’s normal sanitization. Printing decodes one entity layer for angle-containing wording (including escaped inequalities), then escapes the complete result as plain text. Standalone literal entity text remains unchanged; printing never rewrites stored descriptions.

No data patch is needed: `PZ Contract Item.description` already exists as Small Text. A normal app migration syncs its editable metadata for new and saved draft forms without rewriting rows. No production migration was run for this change.

**Print Blank Template** opens a separate two-page printable HTML worksheet from new, saved draft and submitted forms. Use its Print button (or the browser print command) to print or save as PDF. The endpoint requires contract Read and Print permissions. It renders only the bundled logo and fixed empty spaces; it accepts no contract identifier and fetches no records, defaults, payment details, saved clauses or private stamp. It creates no contract, Sales Order, stock or accounting entries.

The worksheet deliberately leaves currency, Incoterm/version, named place, payment split, readiness trigger, loading/export responsibilities and terms blank. Current saved terms include seller-paid Iraqi loading/export obligations; copying those or a default EXW selection into an unsigned blank worksheet would assert obligations the user has not selected. Complete the terms manually or identify an agreed attachment. Ordinary populated print routing and terms snapshots remain unchanged.
