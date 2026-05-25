-- Staging model for the product category translation lookup.
-- 71 rows mapping Portuguese category names to English. Joined into
-- dim_product in the marts layer to expose English-friendly names for
-- the Power BI dashboard and the chatbot.

select
    product_category_name,
    product_category_name_english
from {{ source('olist_raw', 'product_category_name_translation') }}
