-- Order fact table. Grain = order_id (one row per order).
--
-- Joins:
--   stg_orders                    lifecycle timestamps + status
--   int_order_revenue             items + price + freight per order
--   int_order_payments_pivoted    payments aggregated + one column per method
--   stg_order_reviews (agg)       n_reviews + avg_review_score inline
--   stg_customers                 brings customer_unique_id onto the fact
--                                 as a degenerate dimension for RFM
--
-- LEFT JOINs throughout because not every order has items/payments/reviews
-- in the source — those orders should still appear in the fact with zeros.

with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    -- Only need the customer_unique_id; selecting the minimum needed keeps
    -- the join cheap and prevents column-name collisions downstream.
    select customer_id, customer_unique_id from {{ ref('stg_customers') }}
),

revenue as (
    select * from {{ ref('int_order_revenue') }}
),

payments as (
    select * from {{ ref('int_order_payments_pivoted') }}
),

reviews_agg as (
    -- Per-order review summary. Aggregated inline because only fct_orders
    -- consumes it — no need to create an intermediate model.
    -- The 1 row with a NULL order_id (data quality issue surfaced by the
    -- staging tests) is filtered here so the join key stays valid.
    select
        order_id,
        count(*)                       as n_reviews,
        avg(cast(review_score as double)) as avg_review_score
    from {{ ref('stg_order_reviews') }}
    where order_id is not null
    group by order_id
)

select
    -- Primary key
    o.order_id,

    -- Foreign keys / degenerate dimensions
    o.customer_id,
    c.customer_unique_id,
    cast(o.order_purchase_at as date) as order_purchase_date_key,

    -- Status
    o.order_status,

    -- Lifecycle timestamps
    o.order_purchase_at,
    o.order_approved_at,
    o.order_delivered_carrier_at,
    o.order_delivered_customer_at,
    o.order_estimated_delivery_at,

    -- Item + revenue metrics (zero-filled for orders with no items)
    coalesce(r.n_items, 0)            as n_items,
    coalesce(r.total_item_price, 0)   as total_item_price,
    coalesce(r.total_freight, 0)      as total_freight,
    coalesce(r.total_revenue, 0)      as total_revenue,

    -- Payment metrics
    coalesce(p.n_payments, 0)                    as n_payments,
    coalesce(p.total_payment_value, 0)           as total_payment_value,
    coalesce(p.max_installments, 0)              as max_installments,
    coalesce(p.payment_boleto_value, 0)          as payment_boleto_value,
    coalesce(p.payment_credit_card_value, 0)     as payment_credit_card_value,
    coalesce(p.payment_debit_card_value, 0)      as payment_debit_card_value,
    coalesce(p.payment_not_defined_value, 0)     as payment_not_defined_value,
    coalesce(p.payment_voucher_value, 0)         as payment_voucher_value,

    -- Review metrics (NULL avg when no reviews; n_reviews = 0)
    coalesce(rv.n_reviews, 0)         as n_reviews,
    rv.avg_review_score,

    -- Lead times — computed as fractional hours / days using unix epoch
    -- diffs. Portable across SQL dialects, and NULL propagates naturally
    -- when either endpoint is missing.
    (unix_timestamp(o.order_approved_at) - unix_timestamp(o.order_purchase_at)) / 3600.0
        as approval_lead_hours,
    (unix_timestamp(o.order_delivered_carrier_at) - unix_timestamp(o.order_approved_at)) / 86400.0
        as shipping_lead_days,
    (unix_timestamp(o.order_delivered_customer_at) - unix_timestamp(o.order_delivered_carrier_at)) / 86400.0
        as delivery_lead_days,
    (unix_timestamp(o.order_delivered_customer_at) - unix_timestamp(o.order_purchase_at)) / 86400.0
        as total_lead_days,
    (unix_timestamp(o.order_delivered_customer_at) - unix_timestamp(o.order_estimated_delivery_at)) / 86400.0
        as delivery_vs_estimate_days,

    -- On-time flag: TRUE when actual delivery <= estimate. NULL while not delivered yet.
    case
        when o.order_delivered_customer_at is null then null
        when o.order_delivered_customer_at <= o.order_estimated_delivery_at then true
        else false
    end as is_on_time_delivery

from orders o
left join customers   c  on o.customer_id = c.customer_id
left join revenue     r  on o.order_id    = r.order_id
left join payments    p  on o.order_id    = p.order_id
left join reviews_agg rv on o.order_id    = rv.order_id
