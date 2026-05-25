{#-
    Override dbt's default schema-name behavior.

    Default behavior:
        if a model declares `+schema: foo` in dbt_project.yml,
        the resulting schema is `<target.schema>_foo` (prefix-concat).
    Our behavior:
        - no custom schema  -> use target.schema as-is (olist_dev / olist_prod)
        - custom schema set -> use it literally, no prefix

    Why: we control dev/prod separation via env vars in profiles.yml
    (DBT_SCHEMA_DEV / DBT_SCHEMA_PROD), not via per-model custom schemas.
    Prefix-concat would produce names like `olist_dev_marts` which is noise.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
