{#-
    SCD type 2 snapshot of sellers.

    Detects changes in (seller_city, seller_state) using the `check` strategy
    and persists every historical version of each row with the system
    columns dbt_valid_from / dbt_valid_to / dbt_scd_id automatically added
    by dbt.

    Lands in `<target.schema>_snapshots` (configured in dbt_project.yml),
    so dev runs accumulate history in `olist_dev_snapshots.snapshot_sellers`
    and prod runs in `olist_prod_snapshots.snapshot_sellers`.

    `invalidate_hard_deletes=true` flags sellers that disappear from the
    source as deleted by setting dbt_valid_to on their current version,
    rather than silently leaving them as "current".
-#}

{% snapshot snapshot_sellers %}

    {{
        config(
            unique_key='seller_id',
            strategy='check',
            check_cols=['seller_city', 'seller_state'],
            invalidate_hard_deletes=true,
        )
    }}

    select
        seller_id,
        seller_zip_code_prefix,
        seller_city,
        seller_state
    from {{ source('olist_raw', 'olist_sellers_dataset') }}

{% endsnapshot %}
