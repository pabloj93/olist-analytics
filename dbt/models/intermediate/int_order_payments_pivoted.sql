-- Per-order payment summary with a pivoted column per payment method.
-- Aggregates `stg_order_payments` (one row per payment-installment) into
-- one row per order.
--
-- The pivot_payment_methods macro expands at compile time into one
-- `payment_<method>_value` SUM column per distinct payment_type found
-- in the staging model (currently 5: credit_card, boleto, voucher,
-- debit_card, not_defined). If a new method ever appears in the source,
-- the column set updates automatically on the next dbt build.

select
    order_id,
    count(*)                          as n_payments,
    sum(payment_value)                as total_payment_value,
    max(payment_installments)         as max_installments,
    {{ pivot_payment_methods('payment_value') }}
from {{ ref('stg_order_payments') }}
group by order_id
