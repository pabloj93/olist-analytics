-- Staging model for the order payments source.
-- Composite primary key: (order_id, payment_sequential).
-- `payment_type` is kept as-is here (e.g. 'credit_card', 'boleto', 'voucher',
-- 'debit_card', 'not_defined'). Any value-normalization happens in marts.

select
    order_id,
    cast(payment_sequential as int) as payment_sequential,
    payment_type,
    cast(payment_installments as int) as payment_installments,
    cast(payment_value as double) as payment_value
from {{ source('olist_raw', 'olist_order_payments_dataset') }}
