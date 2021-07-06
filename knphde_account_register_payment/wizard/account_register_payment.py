

from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    
    _inherit = "account.payment.register"
    
    payment_type = fields.Selection([
        ('outbound', 'Send Money'),
        ('inbound', 'Receive Money'),
    ], string='Payment Type', store=True, copy=False,
        compute='_compute_from_lines')
    partner_type = fields.Selection([
        ('customer', 'Customer'),
        ('supplier', 'Vendor'),
    ], store=True, copy=False,
        compute='_compute_from_lines')
    source_amount = fields.Monetary(
        string="Amount to Pay (company currency)", store=True, copy=False,
        currency_field='company_currency_id',
        compute='_compute_from_lines')
    source_amount_currency = fields.Monetary(
        string="Amount to Pay (foreign currency)", store=True, copy=False,
        currency_field='source_currency_id',
        compute='_compute_from_lines')
    source_currency_id = fields.Many2one('res.currency',
        string='Source Currency', store=True, copy=False,
        compute='_compute_from_lines',
        help="The payment's currency.")
    can_edit_wizard = fields.Boolean(store=True, copy=False,
        compute='_compute_from_lines',
        help="Technical field used to indicate the user can edit the wizard content such as the amount.")
    can_group_payments = fields.Boolean(store=True, copy=False,
        compute='_compute_from_lines',
        help="Technical field used to indicate the user can see the 'group_payments' box.")
    # company_id = fields.Many2one('res.company', store=True, copy=False,
    #     compute='_compute_from_lines')
    company_id = fields.Many2one('res.company', store=True, copy=False, compute=False, domain = lambda self: "[('id','in',%s)]" % self._context.get('allowed_company_ids'))
    partner_id = fields.Many2one('res.partner',
        string="Customer/Vendor", store=True, copy=False, ondelete='restrict',
        compute='_compute_from_lines')
    journal_id = fields.Many2one('account.journal', store=True, readonly=False,
        compute=False,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]")
    group_payment = fields.Boolean(string="Group Payments", store=True, readonly=False,
        compute=False,
        help="Only one payment will be created by partner (bank)/ currency.", default=True)
    
    invoice_bill_ids = fields.Many2many("unique.invoice.bills",'unique_invoice_bills_acc_pay_reg_rel','invoice_bill_id','account_payment_register_id',"Unique Invoices/Bills")
    
    
    def _get_batches(self):
        ''' Group the account.move.line linked to the wizard together.
        :return: A list of batches, each one containing:
            * key_values:   The key as a dictionary used to group the journal items together.
            * moves:        An account.move recordset.
        '''
        self.ensure_one()

        lines = self.line_ids._origin

        # if len(lines.company_id) > 1:
        #     raise UserError(_("You can't create payments for entries belonging to different companies."))
        if not lines:
            raise UserError(_("You can't open the register payment wizard without at least one receivable/payable line."))

        batches = {}
        for line in lines:
            batch_key = self._get_line_batch_key(line)
            serialized_key = '-'.join(str(v) for v in batch_key.values())
            # serialized_key = '-'.join(str(v) for k,v in batch_key.items() if not k == 'account_id')
            batches.setdefault(serialized_key, {
                'key_values': batch_key,
                'lines': self.env['account.move.line'],
            })
            batches[serialized_key]['lines'] += line
        return list(batches.values())

    @api.model
    def _get_wizard_values_from_batch(self, batch_result):
        ''' Extract values from the batch passed as parameter (see '_get_batches')
        to be mounted in the wizard view.
        :param batch_result:    A batch returned by '_get_batches'.
        :return:                A dictionary containing valid fields
        '''
        key_values = batch_result['key_values']
        lines = batch_result['lines']
        company = lines[0].company_id

        source_amount = abs(sum(lines.mapped('amount_residual')))
        if key_values['currency_id'] == company.currency_id.id:
            source_amount_currency = source_amount
        else:
            source_amount_currency = abs(sum(lines.mapped('amount_residual_currency')))

        return {
            # 'company_id': company.id,
            'partner_id': key_values['partner_id'],
            'partner_type': key_values['partner_type'],
            'payment_type': key_values['payment_type'],
            'source_currency_id': key_values['currency_id'],
            'source_amount': source_amount,
            'source_amount_currency': source_amount_currency,
        }

    @api.depends('line_ids')
    def _compute_from_lines(self):
        ''' Load initial values from the account.moves passed through the context. '''
        for wizard in self:
            batches = wizard._get_batches()
            batch_result = batches[0]
            wizard_values_from_batch = wizard._get_wizard_values_from_batch(batch_result)
            if len(batches) == 1:
                # == Single batch to be mounted on the view ==
                wizard.update(wizard_values_from_batch)

                wizard.can_edit_wizard = True
                wizard.can_group_payments = len(batch_result['lines']) != 1
            else:
                # == Multiple batches: The wizard is not editable  ==
                wizard.update({
                    # 'company_id': batches[0]['lines'][0].company_id.id,
                    'partner_id': False or wizard_values_from_batch['partner_id'],
                    'partner_type': False or wizard_values_from_batch['partner_type'],
                    'payment_type': wizard_values_from_batch['payment_type'],
                    'source_currency_id': False,
                    'source_amount': False,
                    'source_amount_currency': False,
                })
                wizard.can_edit_wizard = False
                wizard.can_group_payments = any(len(batch_result['lines']) != 1 for batch_result in batches)
    
    @api.model
    def default_get(self, fields_list):
        # OVERRIDE
        res = {'payment_date': datetime.now().date(), 'payment_difference_handling': 'open', 'writeoff_label': 'Write-Off'}
        if 'line_ids' in fields_list and 'line_ids' not in res:

            # Retrieve moves to pay from the context.

            if self._context.get('active_model') == 'account.move':
                lines = self.env['account.move'].browse(self._context.get('active_ids', [])).line_ids
            elif self._context.get('active_model') == 'account.move.line':
                lines = self.env['account.move.line'].browse(self._context.get('active_ids', []))
            else:
                raise UserError(_(
                    "The register payment wizard should only be called on account.move or account.move.line records."
                ))

            # Keep lines having a residual amount to pay.
            available_lines = self.env['account.move.line']
            for line in lines:
                if line.move_id.state != 'posted':
                    raise UserError(_("You can only register payment for posted journal entries."))

                if line.account_internal_type not in ('receivable', 'payable'):
                    continue
                if line.currency_id:
                    if line.currency_id.is_zero(line.amount_residual_currency):
                        continue
                else:
                    if line.company_currency_id.is_zero(line.amount_residual):
                        continue
                available_lines |= line
            unique_partner_list = []
            for line in available_lines:
                if line.partner_id.id not in unique_partner_list:
                    unique_partner_list.append(line.partner_id.id)
            partner_dict = {}
            for partner_id in unique_partner_list:
                companylist=[]
                recordlist=[]
                payment_amount = 0
                for line in available_lines:
                    if line.partner_id.id == partner_id:
                        recordlist.append(line.move_id.id)
                        payment_amount += ((line.credit if line.debit == 0 else line.debit) or (line.debit if line.credit == 0 else line.credit))
                        if line.company_id not in companylist:
                            companylist.append(line.company_id)
                partner_dict.update({partner_id:{'company_list': companylist, 'record_list': recordlist, 'payment_amount': payment_amount}})
            unique_invoice_bills_ids = self.env['unique.invoice.bills']
            for k, v in partner_dict.items():
                for comp in v['company_list']:
                    move_ids = self.env['account.move'].search([('id', 'in', v['record_list']),('company_id','=',comp.id)])
                    total_amount = 0.0
                    for mv in move_ids:
                        total_amount += mv.amount_total
                    unique_inv_bill_id = self.env['unique.invoice.bills'].create({'partner_id': k, 'account_move_ids': [(6,0,move_ids.ids)], 'company_id': comp.id, 'total_amount': total_amount})
                    unique_invoice_bills_ids |= unique_inv_bill_id
            # Check.
            # available_lines = self.env['account.move.line']
            # for k, v in partner_dict.items():
            #     print ("key --->>", k)
            #     print ("value --->>", v)
            #     if len(v['company_list']) > 1:
            #         for rec in v['record_list']:
            #             available_lines |= rec
            #     if len(v['company_list']) == 1:
            #         for rec in v['record_list']:
            #             print ("rec ****************************--------->>", rec)
            
            if not available_lines:
                raise UserError(_("You can't register a payment because there is nothing left to pay on the selected journal items."))
            # if len(lines.company_id) > 1:
            #     raise UserError(_("You can't create payments for entries belonging to different companies."))
            if len(set(available_lines.mapped('account_internal_type'))) > 1:
                raise UserError(_("You can't register payments for journal items being either all inbound, either all outbound."))

            res['line_ids'] = [(6, 0, available_lines.ids)]
            res['invoice_bill_ids'] = [(6, 0, unique_invoice_bills_ids.ids)]
        
        # res = super().default_get(fields_list)
        print ("res --->>", res)
        return res

    def _create_payments(self):
        self.ensure_one()
        batches = self._get_batches()
        edit_mode = self.can_edit_wizard and (len(batches[0]['lines']) == 1 or self.group_payment)

        to_reconcile = []
        if edit_mode:
            payment_vals = self._create_payment_vals_from_wizard()
            payment_vals_list = [payment_vals]
            to_reconcile.append(batches[0]['lines'])
        else:
            # Don't group payments: Create one batch per move.
            if not self.group_payment:
                new_batches = []
                for batch_result in batches:
                    for line in batch_result['lines']:
                        new_batches.append({
                            **batch_result,
                            'lines': line,
                        })
                batches = new_batches

            payment_vals_list = []
            for batch_result in batches:
                payment_vals_list.append(self._create_payment_vals_from_batch(batch_result))
                to_reconcile.append(batch_result['lines'])
        
        payments = self.env['account.payment'].create(payment_vals_list)
        
        #create intercompany journal entries if the payment company and journal item entry is different.
        for inv_bill in self.invoice_bill_ids:
            journal_lines = []
            if inv_bill.company_id != self.company_id:
                #search intercompany account
                move_type = inv_bill.account_move_ids.mapped('move_type')[0]
                int_comp_acc_id = self.env['account.account'].search([('name','ilike','Intercompany'),('company_id','=',inv_bill.company_id.id)], limit=1)
                acc_rec_id = self.env['account.account'].search([('name','ilike','Account Receivable'),('company_id','=',inv_bill.company_id.id)], limit=1)
                acc_pay_id = self.env['account.account'].search([('name','ilike','Account Payable'),('company_id','=',inv_bill.company_id.id)], limit=1)
                acc_journal_id = self.env['account.journal'].search([('name','ilike',self.journal_id.name),('company_id','=',inv_bill.company_id.id)], limit=1)
                if not int_comp_acc_id:
                    raise UserError(_("Please create an intercompany account!"))
                if not acc_rec_id:
                    raise UserError(_("Please create a receivable account for %s company!",inv_bill.company_id.id))
                if not acc_pay_id:
                    raise UserError(_("Please create a payable account for %s company!",inv_bill.company_id.id))
                if not acc_journal_id:
                    raise UserError(_("Please create an account journal for %s company!",inv_bill.company_id.id))
                #Vendor Bill or Refund
                if move_type in ['in_invoice', 'in_refund']:
                    journal_lines.append((0, 0, {
                        'account_id': int_comp_acc_id.id,
                        'debit': inv_bill.total_amount,
                        'credit': 0
                    }))
                    journal_lines.append((0, 0, {
                        'account_id': acc_pay_id.id,
                        'debit': 0,
                        'credit': inv_bill.total_amount
                    }))
                if move_type in ['out_invoice','out_refund']:
                    journal_lines.append((0, 0, {
                        'account_id': int_comp_acc_id.id,
                        'debit': 0,
                        'credit': inv_bill.total_amount
                    }))
                    journal_lines.append((0, 0, {
                        'account_id': acc_rec_id.id,
                        'debit': inv_bill.total_amount,
                        'credit': 0
                    }))
                #Post the intercompany journal entry after creating it
                inter_comp_journal_entry = self.env['account.move'].create({
                        'partner_id': inv_bill.partner_id.id,
                        'date': self.payment_date,
                        'invoice_date_due': self.payment_date,
                        'company_id': inv_bill.company_id.id,
                        'journal_id': acc_journal_id.id,
                        'move_type': 'entry',
                        'name': False,
                        'ref': '/',
                        'line_ids': journal_lines
                    })
                inter_comp_journal_entry.action_post()

        
        # If payments are made using a currency different than the source one, ensure the balance match exactly in
        # order to fully paid the source journal items.
        # For example, suppose a new currency B having a rate 100:1 regarding the company currency A.
        # If you try to pay 12.15A using 0.12B, the computed balance will be 12.00A for the payment instead of 12.15A.
        if edit_mode:
            for payment, lines in zip(payments, to_reconcile):
                # Batches are made using the same currency so making 'lines.currency_id' is ok.
                if payment.currency_id != lines.currency_id:
                    liquidity_lines, counterpart_lines, writeoff_lines = payment._seek_for_lines()
                    source_balance = abs(sum(lines.mapped('amount_residual')))
                    payment_rate = liquidity_lines[0].amount_currency / liquidity_lines[0].balance
                    source_balance_converted = abs(source_balance) * payment_rate

                    # Translate the balance into the payment currency is order to be able to compare them.
                    # In case in both have the same value (12.15 * 0.01 ~= 0.12 in our example), it means the user
                    # attempt to fully paid the source lines and then, we need to manually fix them to get a perfect
                    # match.
                    payment_balance = abs(sum(counterpart_lines.mapped('balance')))
                    payment_amount_currency = abs(sum(counterpart_lines.mapped('amount_currency')))
                    if not payment.currency_id.is_zero(source_balance_converted - payment_amount_currency):
                        continue

                    delta_balance = source_balance - payment_balance

                    # Balance are already the same.
                    if self.company_currency_id.is_zero(delta_balance):
                        continue

                    # Fix the balance but make sure to peek the liquidity and counterpart lines first.
                    debit_lines = (liquidity_lines + counterpart_lines).filtered('debit')
                    credit_lines = (liquidity_lines + counterpart_lines).filtered('credit')

                    payment.move_id.write({'line_ids': [
                        (1, debit_lines[0].id, {'debit': debit_lines[0].debit + delta_balance}),
                        (1, credit_lines[0].id, {'credit': credit_lines[0].credit + delta_balance}),
                    ]})

        payments.action_post()

        domain = [('account_internal_type', 'in', ('receivable', 'payable')), ('reconciled', '=', False)]
        for payment, lines in zip(payments, to_reconcile):

            # When using the payment tokens, the payment could not be posted at this point (e.g. the transaction failed)
            # and then, we can't perform the reconciliation.
            if payment.state != 'posted':
                continue

            payment_lines = payment.line_ids.filtered_domain(domain)
            for account in payment_lines.account_id:
                (payment_lines + lines)\
                    .filtered_domain([('account_id', '=', account.id), ('reconciled', '=', False)])\
                    .reconcile()

        return payments
    
    
    @api.onchange('company_id')
    def _onchange_company_id(self):
        domain = [
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', self.company_id.id),
            ]
        journal = None
        if self.source_currency_id:
            journal = self.env['account.journal'].search(domain + [('currency_id', '=', self.source_currency_id.id)])
        if not journal:
            journal = self.env['account.journal'].search(domain)
        res = {}
        res['domain'] = {'journal_id': [('id','in',journal.ids)]}
        return res
    
class UniqueInvoiceBill(models.TransientModel):
    
    _name = "unique.invoice.bills"
    _description = 'Unique Invoice/Bill'
    
    partner_id = fields.Many2one("res.partner")
    account_move_ids = fields.Many2many("account.move",'unique_invoice_bill_account_move_rel','unique_inv_bill_id','account_move_id', "Moves")
    company_id = fields.Many2one("res.company", string="Company")
    total_amount = fields.Float(string="Amount")