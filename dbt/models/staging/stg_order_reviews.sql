-- Staging model for the order reviews source.
-- `review_id` is the natural primary key (one review per order in the vast
-- majority of cases; the few duplicates are downstream's problem, not staging's).
-- Comment fields are in Portuguese and frequently NULL — keep as-is here.

select
    review_id,
    order_id,
    cast(review_score as int) as review_score,
    review_comment_title,
    review_comment_message,
    cast(review_creation_date as timestamp) as review_creation_at,
    cast(review_answer_timestamp as timestamp) as review_answer_at
from {{ source('olist_raw', 'olist_order_reviews_dataset') }}
