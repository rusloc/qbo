-- Line explosion (spec 3.1) and sign normalization (spec 3.2) for the posting transactions.
--
-- One row per element of payload -> 'Line', every DetailType, posting or not. The
-- accepted_values test on detail_type fails on types the spec does not map (e.g. GroupLineDetail
-- bundles) instead of dropping them silently.
-- line_num: 1-based position in the Line array. QBO sends no Id / LineNum on SubTotal and
--   Discount lines, and JournalEntry line Ids start at "0".
-- account: SalesItem -> the line's ItemAccountRef (the account QBO posted to), else the item's
--   current IncomeAccountRef (USER 2026-09-26, spec deviation; applies to Invoice, SalesReceipt,
--   CreditMemo and RefundReceipt alike); ItemBasedExpense -> Item.ExpenseAccountRef;
--   AccountBasedExpense / JournalEntry -> AccountRef; Discount -> DiscountAccountRef.
-- posting_type (side of that account): sales docs credit income and debit discounts; expense
--   docs debit the expense account; credit docs flip (CreditMemo, RefundReceipt, and Purchase
--   with Credit = true, a credit-card credit); JournalEntry lines carry PostingType.
-- amount_signed: credit-natural accounts (Revenue, Liability, Equity) are positive on credit,
--   debit-natural accounts (Expense, Asset) positive on debit. Null on non-posting lines.
-- Deposit and VendorCredit are landed raw but not transformed yet (not in spec 3.1).
with txn as (
    select
         e.entity_type                                             txn_type
        ,e.qbo_id                                                  txn_qbo_id
        ,e.payload                                                 payload
        ,(e.payload ->> 'TxnDate')::date                           txn_date
        ,case
             when e.entity_type in ('CreditMemo', 'RefundReceipt')
                 then true
             when e.entity_type = 'Purchase'
                 and coalesce((e.payload ->> 'Credit')::boolean, false)
                 then true
             else false
         end                                                       is_credit_doc
        ,e.is_voided                                               is_voided
        ,e.is_deleted                                              is_deleted
        ,e.synced_at                                               synced_at
    from {{ ref('stg_entity_latest') }} e
    where 1=1
        and e.entity_type in (
             'Invoice'
            ,'SalesReceipt'
            ,'CreditMemo'
            ,'RefundReceipt'
            ,'Bill'
            ,'Purchase'
            ,'JournalEntry'
        )
)
,line as (
    select
         t.txn_type                                                txn_type
        ,t.txn_qbo_id                                              txn_qbo_id
        ,j.line_num::integer                                       line_num
        ,t.txn_date                                                txn_date
        ,t.payload                                                 payload
        ,t.is_credit_doc                                           is_credit_doc
        ,t.is_voided                                               is_voided
        ,t.is_deleted                                              is_deleted
        ,t.synced_at                                               synced_at
        ,j.line ->> 'DetailType'                                   detail_type
        ,j.line -> (j.line ->> 'DetailType')                       detail
        ,(j.line ->> 'Amount')::numeric(15,2)                      amount
        ,j.line ->> 'Description'                                  description
    from txn t
    cross join lateral jsonb_array_elements(t.payload -> 'Line') with ordinality j(line, line_num)
)
,resolved as (
    select
         l.txn_type                                                txn_type
        ,l.txn_qbo_id                                              txn_qbo_id
        ,l.line_num                                                line_num
        ,l.detail_type                                             detail_type
        ,l.detail_type in (
             'SalesItemLineDetail'
            ,'AccountBasedExpenseLineDetail'
            ,'ItemBasedExpenseLineDetail'
            ,'JournalEntryLineDetail'
            ,'DiscountLineDetail'
         )                                                         is_posting
        ,l.txn_date                                                txn_date
        ,case l.detail_type
             when 'SalesItemLineDetail'
                 then coalesce(
                          l.detail -> 'ItemAccountRef' ->> 'value'
                         ,i.income_account_qbo_id
                      )
             when 'ItemBasedExpenseLineDetail'
                 then i.expense_account_qbo_id
             when 'AccountBasedExpenseLineDetail'
                 then l.detail -> 'AccountRef' ->> 'value'
             when 'JournalEntryLineDetail'
                 then l.detail -> 'AccountRef' ->> 'value'
             when 'DiscountLineDetail'
                 then l.detail -> 'DiscountAccountRef' ->> 'value'
         end                                                       account_qbo_id
        ,case
             when l.detail_type = 'JournalEntryLineDetail'
                 then l.detail ->> 'PostingType'
             when l.detail_type = 'SalesItemLineDetail'
                 then case
                          when l.is_credit_doc
                              then 'Debit'
                          else 'Credit'
                      end
             when l.detail_type in (
                  'DiscountLineDetail'
                 ,'AccountBasedExpenseLineDetail'
                 ,'ItemBasedExpenseLineDetail'
             )
                 then case
                          when l.is_credit_doc
                              then 'Credit'
                          else 'Debit'
                      end
         end                                                       posting_type
        ,l.amount                                                  amount
        ,coalesce(
             l.detail -> 'CustomerRef' ->> 'value'
            ,case
                 when l.detail -> 'Entity' ->> 'Type' = 'Customer'
                     then l.detail -> 'Entity' -> 'EntityRef' ->> 'value'
             end
            ,l.payload -> 'CustomerRef' ->> 'value'
            ,case
                 when l.payload -> 'EntityRef' ->> 'type' = 'Customer'
                     then l.payload -> 'EntityRef' ->> 'value'
             end
         )                                                         customer_qbo_id
        ,coalesce(
             case
                 when l.detail -> 'Entity' ->> 'Type' = 'Vendor'
                     then l.detail -> 'Entity' -> 'EntityRef' ->> 'value'
             end
            ,l.payload -> 'VendorRef' ->> 'value'
            ,case
                 when l.payload -> 'EntityRef' ->> 'type' = 'Vendor'
                     then l.payload -> 'EntityRef' ->> 'value'
             end
         )                                                         vendor_qbo_id
        ,coalesce(
             l.detail -> 'ClassRef' ->> 'value'
            ,l.payload -> 'ClassRef' ->> 'value'
         )                                                         class_qbo_id
        ,coalesce(
             nullif(l.description, '')
            ,l.payload ->> 'PrivateNote'
         )                                                         memo
        ,l.is_voided                                               is_voided
        ,l.is_deleted                                              is_deleted
        ,l.synced_at                                               synced_at
    from line l
    left join {{ ref('stg_item') }} i
        on i.qbo_id = l.detail -> 'ItemRef' ->> 'value'
)
select
     r.txn_type                                                    txn_type
    ,r.txn_qbo_id                                                  txn_qbo_id
    ,r.line_num                                                    line_num
    ,r.detail_type                                                 detail_type
    ,r.is_posting                                                  is_posting
    ,r.txn_date                                                    txn_date
    ,r.account_qbo_id                                              account_qbo_id
    ,a.classification                                              account_classification
    ,r.posting_type                                                posting_type
    ,r.amount                                                      amount
    ,case
         when not r.is_posting
             then null
         when a.classification in ('Revenue', 'Liability', 'Equity')
             then case
                      when r.posting_type = 'Credit'
                          then r.amount
                      else -r.amount
                  end
         when a.classification in ('Expense', 'Asset')
             then case
                      when r.posting_type = 'Debit'
                          then r.amount
                      else -r.amount
                  end
     end::numeric(15,2)                                            amount_signed
    ,r.customer_qbo_id                                             customer_qbo_id
    ,r.vendor_qbo_id                                               vendor_qbo_id
    ,r.class_qbo_id                                                class_qbo_id
    ,r.memo                                                        memo
    ,r.is_voided                                                   is_voided
    ,r.is_deleted                                                  is_deleted
    ,r.synced_at                                                   synced_at
from resolved r
left join {{ ref('stg_account') }} a
    on a.qbo_id = r.account_qbo_id
