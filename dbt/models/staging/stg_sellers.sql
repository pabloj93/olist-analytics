-- Staging model for the sellers source.
-- Same zip-code-as-string treatment as customers, to preserve leading zeros.

select
    seller_id,
    cast(seller_zip_code_prefix as string) as seller_zip_code_prefix,
    seller_city,
    seller_state
from {{ source('olist_raw', 'olist_sellers_dataset') }}
