-- Calendar dimension. One row per day spanning the Olist data window
-- (2016-09 -> 2018-10) plus generous buffer on both sides for future use.
--
-- Built from dbt_utils.date_spine, which generates a contiguous series of
-- dates between two literals. Derived attributes (year, month, quarter,
-- weekday, weekend flag) are computed once here so every BI/chatbot query
-- can join instead of recomputing date functions.

with raw_dates as (
    {{ dbt_utils.date_spine(
        datepart='day',
        start_date="cast('2016-01-01' as date)",
        end_date="cast('2020-01-01' as date)"
    ) }}
)

select
    cast(date_day as date)                       as date_key,
    extract(year from date_day)                  as year,
    extract(quarter from date_day)               as quarter,
    extract(month from date_day)                 as month_number,
    date_format(date_day, 'MMMM')                as month_name,
    extract(week from date_day)                  as week_of_year,
    extract(day from date_day)                   as day_of_month,
    extract(dayofweek from date_day)             as day_of_week_number,
    date_format(date_day, 'EEEE')                as day_name,
    case
        when extract(dayofweek from date_day) in (1, 7) then true
        else false
    end                                          as is_weekend
from raw_dates
