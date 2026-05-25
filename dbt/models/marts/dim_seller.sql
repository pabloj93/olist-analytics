-- Seller dimension. Grain = seller_id.
-- Same LEFT JOIN pattern as dim_customer to attach lat/long without
-- dropping sellers whose zip prefix is missing from the geolocation source.

select
    s.seller_id,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    g.latitude    as seller_latitude,
    g.longitude   as seller_longitude
from {{ ref('stg_sellers') }} s
left join {{ ref('int_geolocation_centroid') }} g
    on s.seller_zip_code_prefix = g.zip_code_prefix
