-- Staging model for the geolocation source.
-- Multiple (lat, lng) pairs exist per zip code prefix (one per address sample).
-- Keep all rows here; deduplication / centroid logic belongs in the
-- intermediate layer where the join semantics are decided.

select
    cast(geolocation_zip_code_prefix as string) as geolocation_zip_code_prefix,
    cast(geolocation_lat as double) as geolocation_lat,
    cast(geolocation_lng as double) as geolocation_lng,
    geolocation_city,
    geolocation_state
from {{ source('olist_raw', 'olist_geolocation_dataset') }}
