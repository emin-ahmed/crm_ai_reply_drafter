# Part of the crm_ai_reply_drafter module. See LICENSE file for details.
{
    'name': 'AI Reply Drafter for CRM',
    'version': '19.0.1.0.0',
    'summary': 'Draft personalized email replies to leads with an LLM, '
               'streamed live into the email composer',
    'description': """
AI Reply Drafter for Odoo CRM
=============================

Adds a **Draft Reply** button to the lead/opportunity form. The module reads
the lead's data and its full chatter conversation, sends them to a configurable
LLM (OpenAI, Anthropic or local Ollama) with a configurable system prompt, and
streams back a personalized email draft that pre-fills Odoo's email composer.

* The salesperson always reviews and sends — the module never auto-sends.
* One provider per configuration; the API key lives in Settings, never in code.
* Every generation is logged with token counts, a cost estimate, the lead,
  the user and a timestamp.

Built on Odoo 19 Community.
""",
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'author': 'Emin Ahmed',
    'maintainer': 'Emin Ahmed',
    'website': 'https://github.com/emin-ahmed',
    'support': 'emin.talebahmed@gmail.com',
    'development_status': 'Beta',
    # First image is the App Store cover; replace demo.gif with your recording.
    'images': [
        'static/description/banner.png',
        'static/description/demo.gif',
    ],
    'depends': ['crm', 'mail'],
    # NOTE: provider SDKs (anthropic / openai / requests) are intentionally NOT
    # declared in external_dependencies. Only one provider is used per install,
    # so requiring all three would needlessly block installation. The provider
    # clients import their SDK lazily and raise a clear UserError if it's
    # missing. See services/providers.py.
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'views/ai_reply_log_views.xml',
        'views/crm_lead_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/ai_reply_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'crm_ai_reply_drafter/static/src/**/*.js',
            'crm_ai_reply_drafter/static/src/**/*.xml',
            'crm_ai_reply_drafter/static/src/**/*.scss',
        ],
    },
    'application': True,
    'installable': True,
}
