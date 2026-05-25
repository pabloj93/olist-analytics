-- Product dimension. Grain = product_id.
-- Enriched with the English category name from the translation lookup
-- and a derived volume metric (cm³) handy for shipping analyses.

select
    p.product_id,

    -- Category: keep both names. Portuguese is the source value; English
    -- is what the Power BI dashboard and chatbot will surface to users.
    p.product_category_name                                      as category_pt,
    coalesce(t.product_category_name_english, 'unknown')         as category_en,

    p.product_name_length,
    p.product_description_length,
    p.product_photos_qty,
    -- Convenience boolean for "did this product upload at least one photo?"
    coalesce(p.product_photos_qty > 0, false)                    as has_photos,

    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    -- Estimated package volume — multiplies three dimensions; nulls
    -- propagate if any dimension is missing, which is the desired behavior.
    p.product_length_cm * p.product_height_cm * p.product_width_cm
        as product_volume_cm3

from {{ ref('stg_products') }} p
left join {{ ref('stg_product_category_translation') }} t
    on p.product_category_name = t.product_category_name
