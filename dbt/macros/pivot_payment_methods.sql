{#-
    Pivot order_payment rows into one column per payment_type at compile time.

    Usage (inside a GROUP BY order_id aggregation on stg_order_payments):
        {{ pivot_payment_methods('payment_value') }}

    Expands at compile time into:
        sum(case when payment_type = 'boleto'      then payment_value else 0 end) as payment_boleto_value,
        sum(case when payment_type = 'credit_card' then payment_value else 0 end) as payment_credit_card_value,
        ...

    Why dynamic over hardcoded:
        dbt_utils.get_column_values queries the staging model at compile time
        for the actual distinct payment_type values, so if the source ever
        gains a new payment method (e.g. 'pix') the macro picks it up
        automatically. Hyphens / spaces in values are replaced with `_`
        because they cannot appear in column names.

    Arguments:
        value_column   the numeric column to sum (default 'payment_value')
        relation       relation to inspect (default ref('stg_order_payments'))
        method_column  the column holding the pivot values (default 'payment_type')
-#}
{% macro pivot_payment_methods(value_column='payment_value',
                               relation=None,
                               method_column='payment_type') -%}

    {%- if relation is none -%}
        {%- set relation = ref('stg_order_payments') -%}
    {%- endif -%}

    {%- set methods = dbt_utils.get_column_values(
        table=relation,
        column=method_column,
        order_by=method_column,
    ) -%}

    {%- for method in methods -%}
        {%- set safe_method = method | replace('-', '_') | replace(' ', '_') -%}
        sum(case when {{ method_column }} = '{{ method }}' then {{ value_column }} else 0 end) as payment_{{ safe_method }}_value
        {%- if not loop.last -%},{{ '\n        ' }}{%- endif -%}
    {%- endfor -%}

{%- endmacro %}
