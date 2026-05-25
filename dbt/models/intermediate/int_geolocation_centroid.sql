-- Collapse the ~1M geolocation rows into one (lat, lng) per zip code prefix.
-- Used by dim_customer and dim_seller to attach a single representative
-- coordinate pair to each location.
--
-- Materialized as a table (overrides the intermediate default of ephemeral)
-- because the underlying aggregation touches 1M rows and is consumed by
-- multiple dims — paying the cost once is cheaper than inlining the CTE
-- into every downstream model.

{{ config(materialized='table') }}

select
    geolocation_zip_code_prefix     as zip_code_prefix,

    -- Centroid of the (lat, lng) samples per zip. Olist geolocation has
    -- one sample per street address, so the mean approximates the zip's
    -- center well enough for map visuals.
    avg(geolocation_lat)            as latitude,
    avg(geolocation_lng)            as longitude,

    -- Pick a single representative city/state per zip. Per-zip names are
    -- consistent in the source for ~99% of cases; MAX gives us a
    -- deterministic pick when there are tiny variations (typos).
    max(geolocation_city)           as city,
    max(geolocation_state)          as state,

    count(*)                        as n_address_samples
from {{ ref('stg_geolocation') }}
group by geolocation_zip_code_prefix
