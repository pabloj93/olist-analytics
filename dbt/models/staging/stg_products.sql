-- Staging model for the products source.
-- The source has two known column-name typos that we fix here so downstream
-- code uses correct spelling: product_name_lenght -> product_name_length,
-- product_description_lenght -> product_description_length.

select
    product_id,
    product_category_name,
    cast(product_name_lenght as int)        as product_name_length,
    cast(product_description_lenght as int) as product_description_length,
    cast(product_photos_qty as int)         as product_photos_qty,
    cast(product_weight_g as int)           as product_weight_g,
    cast(product_length_cm as int)          as product_length_cm,
    cast(product_height_cm as int)          as product_height_cm,
    cast(product_width_cm as int)           as product_width_cm
from {{ source('olist_raw', 'olist_products_dataset') }}
