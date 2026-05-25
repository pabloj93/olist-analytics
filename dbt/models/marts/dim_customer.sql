-- Customer dimension. Grain = customer_id (per-order surrogate from the
-- source). The stable person-level identifier `customer_unique_id` is kept
-- as an attribute so that person-level analyses (mart_customer_rfm, etc.)
-- can aggregate across multiple customer_ids that map to the same person.
--
-- LEFT JOIN to int_geolocation_centroid is intentional: a customer's zip
-- prefix may not exist in the geolocation source (geo is a sample, not
-- exhaustive). Such customers will have NULL coordinates rather than be
-- dropped.

select
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,
    g.latitude    as customer_latitude,
    g.longitude   as customer_longitude
from {{ ref('stg_customers') }} c
left join {{ ref('int_geolocation_centroid') }} g
    on c.customer_zip_code_prefix = g.zip_code_prefix
