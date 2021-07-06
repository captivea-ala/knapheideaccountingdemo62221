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
        'wizard/account_register_payment_view.xml',
        ],
    'installable': True,
    'application': False,
    'auto_install':False
}
