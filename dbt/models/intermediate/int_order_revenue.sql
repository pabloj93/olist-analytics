-- Per-order revenue summary. Aggregates `stg_order_items` (one row per
-- line item) into one row per order.
--
-- Consumed by fct_orders (direct join) and mart_customer_rfm (via fct).
-- Kept ephemeral (default for intermediate/) since it is cheap to recompute
-- and downstream models can fuse the CTE for free.

select
    order_id,
    count(*)                       as n_items,
    sum(price)                     as total_item_price,
    sum(freight_value)             as total_freight,
    sum(price + freight_value)     as total_revenue,
    min(shipping_limit_at)         as earliest_shipping_limit_at,
    max(shipping_limit_at)         as latest_shipping_limit_at
from {{ ref('stg_order_items') }}
group by order_id
