-- Staging model for the order items source.
-- Composite primary key: (order_id, order_item_id).
-- `shipping_limit_date` arrives as a string timestamp; cast explicitly so
-- downstream date arithmetic does not require per-model parsing.

select
    order_id,
    cast(order_item_id as int) as order_item_id,
    product_id,
    seller_id,
    cast(shipping_limit_date as timestamp) as shipping_limit_at,
    cast(price as double) as price,
    cast(freight_value as double) as freight_value
from {{ source('olist_raw', 'olist_order_items_dataset') }}
