# Part of the crm_ai_reply_assistant module. See LICENSE file for details.
"""Assemble the user-content prompt from a lead and its chatter.

Kept as plain functions (no ORM model) so the prompt assembly is trivially unit
testable: feed it a lead recordset, get back a string. The system prompt itself
comes from configuration and is handled in the service layer.
"""
from odoo.tools import html2plaintext

# Chatter message types that represent real conversation. Plain notes and
# tracking/notification messages are skipped.
CONVERSATION_TYPES = ('comment', 'email')


def _format_lead_fields(lead):
    """Return a human-readable bullet list of the lead's salient fields.

    Only fields that exist and have a value are emitted, so the function
    degrades gracefully across Odoo editions (e.g. ``products of interest`` is
    not a core Community field on ``crm.lead``).
    """
    lines = []

    def add(label, value):
        if value:
            lines.append("- %s: %s" % (label, value))

    add("Lead/Opportunity", lead.name)
    add("Contact name", lead.contact_name or lead.partner_name)
    if lead.partner_id:
        add("Customer", lead.partner_id.display_name)
    add("Email", lead.email_from)
    add("Phone", lead.phone)
    if lead.expected_revenue:
        currency = lead.company_currency.name if lead.company_currency else ''
        add("Expected revenue",
            ("%s %s" % (lead.expected_revenue, currency)).strip())
    add("Probability", "%s%%" % lead.probability if lead.probability else None)
    if lead.tag_ids:
        add("Tags", ", ".join(lead.tag_ids.mapped('name')))
    if lead.source_id:
        add("Source", lead.source_id.name)
    # "Products of interest" is not a core Community field; include it only if
    # some other module added it, so the prompt stays edition-agnostic.
    if 'product_id' in lead._fields and lead.product_id:
        add("Product of interest", lead.product_id.display_name)
    if lead.description:
        add("Internal notes", html2plaintext(lead.description))

    return "\n".join(lines)


def _format_conversation(lead, max_messages):
    """Return the chatter conversation as chronological plain text.

    Takes the most recent ``max_messages`` real conversation messages and
    orders them oldest-first so the model reads the thread naturally.
    """
    messages = lead.message_ids.filtered(
        lambda m: m.message_type in CONVERSATION_TYPES and
        (m.body or m.subject))
    # message_ids is newest-first; take the most recent N, then sort to
    # chronological order. Include id as a tiebreaker because messages posted
    # in the same second share a timestamp.
    recent = messages[:max_messages]
    recent = recent.sorted(key=lambda m: (m.date or m.create_date, m.id))

    blocks = []
    for msg in recent:
        author = msg.author_id.display_name if msg.author_id else (
            msg.email_from or "Unknown")
        when = msg.date or msg.create_date
        body = html2plaintext(msg.body) if msg.body else (msg.subject or "")
        body = body.strip()
        if not body:
            continue
        blocks.append("[%s] %s:\n%s" % (when, author, body))

    return "\n\n".join(blocks)


def build_user_content(lead, max_messages):
    """Build the full user-content prompt for a lead.

    :param lead: a single ``crm.lead`` record
    :param int max_messages: max chatter messages to include
    :returns: the assembled prompt string
    :rtype: str
    """
    fields_block = _format_lead_fields(lead)
    conversation = _format_conversation(lead, max_messages)

    parts = ["## Lead details", fields_block or "(no structured details)"]
    parts.append("## Conversation history (oldest first)")
    parts.append(conversation or "(no prior messages)")
    parts.append(
        "## Task\nWrite the reply email body now, following the system "
        "instructions.")
    return "\n\n".join(parts)
