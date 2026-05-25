-- Item-grain order fact. Composite key: (order_id, order_item_id).
-- One row per line item. Pre-joined with customer, seller, product, date
-- context so the chatbot can answer cross-dimensional questions
-- ("top sellers by state", "top categories by revenue", "average ticket
-- per product category") without joining staging models.
--
-- Why a fact at item grain (in addition to fct_orders at order grain):
--   fct_orders is ideal for order-level metrics (delivery lead times,
--   payment funnel). But sellers and products live at the line-item level —
--   one order can contain items from many sellers, of many products. Any
--   seller- or product-level analytics need the item-grain fact.
--
-- Geographic context is de-normalized for both sides (customer and seller)
-- so map visuals can pick up coordinates without an extra dim join.

with items as (
    select * from {{ ref('stg_order_items') }}
),

orders as (
    select
        order_id,
        customer_id,
        order_status,
        order_purchase_at,
        cast(order_purchase_at as date) as order_purchase_date_key
    from {{ ref('stg_orders') }}
),

customers as (
    select
        customer_id,
        customer_unique_id,
        customer_state,
        customer_city
    from {{ ref('stg_customers') }}
),

sellers as (
    select
        seller_id,
        seller_state,
        seller_city
    from {{ ref('stg_sellers') }}
),

products as (
    -- Re-use the curated dim_product so we expose the English category
    -- and any derived flags (has_photos, volume_cm3) at item grain too.
    select * from {{ ref('dim_product') }}
)

select
    -- --- Composite primary key ---
    i.order_id,
    i.order_item_id,

    -- --- Foreign keys ---
    i.product_id,
    i.seller_id,
    o.customer_id,
    c.customer_unique_id,
    o.order_purchase_date_key,

    -- --- Order context ---
    o.order_status,
    o.order_purchase_at,
    i.shipping_limit_at,

    -- --- Geographic context (denormalized for chatbot + BI speed) ---
    c.customer_state,
    c.customer_city,
    s.seller_state,
    s.seller_city,

    -- --- Product context (de-normalized) ---
    p.category_pt    as product_category_pt,
    p.category_en    as product_category_en,

    -- --- Metrics ---
    i.price,
    i.freight_value,
    i.price + i.freight_value   as item_revenue

from items i
left join orders    o on i.order_id   = o.order_id
left join customers c on o.customer_id = c.customer_id
left join sellers   s on i.seller_id  = s.seller_id
left join products  p on i.product_id = p.product_id
