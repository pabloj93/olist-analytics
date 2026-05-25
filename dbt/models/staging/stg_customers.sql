-- Staging model for the customers source.
-- 1:1 with `olist_customers_dataset`. Renames columns to drop the `customer_`
-- prefix where it is redundant in context, and casts the zip code prefix to
-- string so leading zeros are preserved.

select
    customer_id,
    customer_unique_id,
    cast(customer_zip_code_prefix as string) as customer_zip_code_prefix,
    customer_city,
    customer_state
from {{ source('olist_raw', 'olist_customers_dataset') }}
