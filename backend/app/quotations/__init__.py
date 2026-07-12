"""Sell-side quotation generator.

Turns a customer RFP/inquiry into a priced, client-facing quotation:
  extract.py   -- RFP/images/chat -> requested line items (BomItems)
  assemble.py  -- price the demand from the project matrix + margin -> a version
  render_docx  -- client-facing DOCX (no letterhead)
  render_xlsx  -- internal calculation buildup

See app.api.quotations for the HTTP surface and the memory note
`quotation-generator-feature` for the settled design.
"""
