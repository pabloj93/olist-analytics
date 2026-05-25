-- Staging model for the orders source.
-- One row per order. Five lifecycle timestamps cast to TIMESTAMP for safe
-- date math downstream. `order_estimated_delivery_date` is a date-only value
-- in the source but cast to TIMESTAMP for uniformity.

select
    order_id,
    customer_id,
    order_status,
    cast(order_purchase_timestamp as timestamp)      as order_purchase_at,
    cast(order_approved_at as timestamp)             as order_approved_at,
    cast(order_delivered_carrier_date as timestamp)  as order_delivered_carrier_at,
    cast(order_delivered_customer_date as timestamp) as order_delivered_customer_at,
    cast(order_estimated_delivery_date as timestamp) as order_estimated_delivery_at
from {{ source('olist_raw', 'olist_orders_dataset') }}
