with attribution_touches as (
    select * from {{ ref('attribution_touches') }}
),

-- Linear attribution: every touchpoint in the conversion path is equally
-- important, so each session in the path receives an equal share of the
-- conversion's points and revenue.
linear_attribution as (
    select
        date_trunc('month', converted_at) as date_month,
        utm_source,
        sum(linear_points) as attribution_points,
        sum(linear_revenue) as attribution_revenue
    from attribution_touches
    group by 1, 2
),

ad_spend as (
    select
        date_trunc('month', date_day) as date_month,
        utm_source,
        sum(spend) as total_spend
    from {{ source('playbook', 'ad_spend') }}
    group by 1, 2
)

select
    coalesce(a.date_month, s.date_month) as date_month,
    coalesce(a.utm_source, s.utm_source) as utm_source,
    coalesce(a.attribution_points, 0) as attribution_points,
    coalesce(a.attribution_revenue, 0) as attribution_revenue,
    coalesce(s.total_spend, 0) as total_spend,
    case
        when coalesce(a.attribution_points, 0) > 0
        then coalesce(s.total_spend, 0) / a.attribution_points
        else 0
    end as cost_per_acquisition,
    case
        when coalesce(s.total_spend, 0) > 0
        then a.attribution_revenue / s.total_spend
        else 0
    end as return_on_advertising_spend
from linear_attribution a
full outer join ad_spend s
    on a.date_month = s.date_month
    and a.utm_source = s.utm_source
