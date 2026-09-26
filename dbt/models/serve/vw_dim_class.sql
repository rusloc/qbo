-- Serve view for Power BI (spec 2.4): QBO classes. Facts without a class have class_key null.
select
     c.class_key                                                   class_key
    ,c.qbo_id                                                      qbo_id
    ,c.class_name                                                  class_name
from {{ ref('dim_class') }} c
