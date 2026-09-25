-- EXPECTED SHAPE: one row per (month, utm_source) - REASON: YML grain is date_month + utm_source
-- Linear attribution: every touchpoint in the conversion path is equally important,
-- so each session in the path receives 1/total_sessions of the conversion's points and revenue.

with attribution as (
    select
        cast(date_trunc('month', converted_at) as date) as date_month,
        utm_source,
        sum(linear_points) as attribution_points,
        sum(linear_revenue) as attribution_revenue
    from {{ ref('attribution_touches') }}
    group by 1, 2
),

spend as (
    select
        cast(date_trunc('month', date_day) as date) as date_month,
        utm_source,
        sum(spend) as total_spend
    from {{ source('playbook', 'ad_spend') }}
    group by 1, 2
)

select
    attribution.date_month,
    attribution.utm_source,
    attribution.attribution_points,
    attribution.attribution_revenue,
    coalesce(spend.total_spend, 0) as total_spend,
    coalesce(spend.total_spend, 0) / attribution.attribution_points as cost_per_acquisition,
    attribution.attribution_revenue / coalesce(spend.total_spend, 0) as return_on_advertising_spend
from attribution
left join spend
    on attribution.date_month = spend.date_month
    and attribution.utm_source = spend.utm_source
