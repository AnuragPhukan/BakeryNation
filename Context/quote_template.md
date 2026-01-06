# {{company_name}} — Quotation

**Quote ID:** {{quote_id}}  
**Date:** {{quote_date}}  
**Valid Until:** {{valid_until}}  
**Customer:** {{customer_name}}  
**Project:** {{job_type}} × {{quantity}}  
**Delivery / Due:** {{due_date}}

## Bill of Materials & Labor
| Item | Qty | Unit | Unit Cost ({{currency}}) | Line Cost |
|---|---:|:---:|---:|---:|
{{#lines}}
| {{name}} | {{qty}} | {{unit}} | {{unit_cost}} | {{line_cost}} |
{{/lines}}
| **Labor (@ {{labor_rate}}/h)** | {{labor_hours}} | h | — | {{labor_cost}} |

**Materials Subtotal:** {{materials_subtotal}} {{currency}}  
**Labor Subtotal:** {{labor_cost}} {{currency}}  
**Subtotal (pre-markup):** {{subtotal}} {{currency}}  
**Markup ({{markup_pct}}):** {{markup_value}} {{currency}}  
**Price before VAT:** {{price_before_vat}} {{currency}}  
**VAT ({{vat_pct}}):** {{vat_value}} {{currency}}  
**Total:** **{{total}} {{currency}}**

**Notes:** {{notes}}

---

*Thank you for your business!*
