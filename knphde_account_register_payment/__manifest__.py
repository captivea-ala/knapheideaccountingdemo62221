{
    'name': "Knapheide Account Register Payment",
    'version': "14.0",
    'category': "account",
    'depends': ['account', 'payment_fix_register_token'],
    'author':'konsultoo',
    'website':'https://www.konsultoo.com/',
    'summary'
    'description': """
        Knapheide Account Register Payment
    """,
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_view.xml',
        'views/res_partner_view.xml',
        'wizard/account_register_payment_view.xml',
        ],
    'installable': True,
    'application': False,
    'auto_install':False
}
