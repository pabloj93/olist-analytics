-- Customer-level RFM segmentation. Grain = customer_unique_id (the
-- person-level identifier, not the per-order customer_id).
--
-- Built directly off fct_orders thanks to the customer_unique_id
-- degenerate dimension carried on the fact — no second join needed.
--
-- RFM scoring uses NTILE(5) quintiles (1 = worst, 5 = best):
--   Recency:   days since last purchase (lower = better => higher score)
--   Frequency: count of orders (higher = better)
--   Monetary:  total revenue (higher = better)
--
-- Canceled / unavailable orders are excluded so they don't count toward
-- frequency or monetary value.

with eligible_orders as (
    select
        customer_unique_id,
        order_id,
        order_purchase_at,
        total_revenue
    from {{ ref('fct_orders') }}
    where order_status not in ('canceled', 'unavailable')
      and customer_unique_id is not null
),

per_customer as (
    select
        customer_unique_id,
        count(*)                  as frequency,
        sum(total_revenue)        as monetary,
        min(order_purchase_at)    as first_order_at,
        max(order_purchase_at)    as last_order_at
    from eligible_orders
    group by customer_unique_id
),

reference as (
    -- The recency reference is the most recent purchase in the dataset.
    -- Using a moving "today" would be wrong here since the data is historical.
    select max(last_order_at) as reference_at from per_customer
),

with_recency as (
    select
        pc.*,
        cast(
            (unix_timestamp(ref.reference_at) - unix_timestamp(pc.last_order_at)) / 86400.0
            as int
        ) as recency_days
    from per_customer pc
    cross join reference ref
),

scored as (
    select
        customer_unique_id,
        frequency,
        monetary,
        recency_days,
        first_order_at,
        last_order_at,

        -- NTILE(5) over each metric. Note the ORDER BY direction:
        --   Recency:   smaller days = better => DESC so smallest -> 5
        --   Frequency: larger count = better => ASC so largest -> 5
        --   Monetary:  larger spend = better => ASC so largest -> 5
        ntile(5) over (order by recency_days desc) as recency_score,
        ntile(5) over (order by frequency asc)     as frequency_score,
        ntile(5) over (order by monetary asc)      as monetary_score
    from with_recency
)

select
    customer_unique_id,

    -- Raw metrics
    recency_days,
    frequency,
    monetary,

    -- Lifecycle anchors
    first_order_at,
    last_order_at,

    -- Quintile scores (1..5)
    recency_score,
    frequency_score,
    monetary_score,

    -- Concatenated RFM code, e.g. "555" for the best customers.
    concat(
        cast(recency_score   as string),
        cast(frequency_score as string),
        cast(monetary_score  as string)
    ) as rfm_code,

    -- Segment label following the canonical industry mapping. Most rules
    -- look at R + F first; M acts as the tie-breaker for "Champions" and
    -- "Cant Lose Them".
    case
        when recency_score >= 4 and frequency_score >= 4 and monetary_score >= 4 then 'Champions'
        when recency_score >= 4 and frequency_score >= 3                          then 'Loyal Customers'
        when recency_score >= 4 and frequency_score <= 2                          then 'New Customers'
        when recency_score >= 3 and monetary_score   >= 4                         then 'Potential Loyalists'
        when recency_score <= 2 and frequency_score >= 4 and monetary_score >= 4  then 'Cant Lose Them'
        when recency_score <= 2 and frequency_score >= 3                          then 'At Risk'
        when recency_score <= 2 and frequency_score <= 2                          then 'Lost'
        else 'About to Sleep'
    end as customer_segment

from scored
