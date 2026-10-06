locals {
  cost_queries = {
    monthly_account_service = <<-SQL
      SELECT line_item_usage_account_id, line_item_usage_account_name,
             line_item_product_code, line_item_currency_code,
             SUM(line_item_unblended_cost) AS unblended_cost
      FROM org_billing.cost_usage
      WHERE billing_period = date_format(current_date, '%Y-%m')
      GROUP BY 1, 2, 3, 4
      ORDER BY unblended_cost DESC
    SQL
    daily_current_month = <<-SQL
      SELECT date(line_item_usage_start_date) AS usage_day,
             line_item_currency_code,
             SUM(line_item_unblended_cost) AS unblended_cost
      FROM org_billing.cost_usage
      WHERE billing_period = date_format(current_date, '%Y-%m')
      GROUP BY 1, 2
      ORDER BY 1
    SQL
    usage_dimensions = <<-SQL
      SELECT line_item_usage_account_id, line_item_product_code,
             line_item_usage_type, line_item_operation, pricing_unit,
             SUM(line_item_usage_amount) AS usage_amount,
             line_item_currency_code,
             SUM(line_item_unblended_cost) AS unblended_cost
      FROM org_billing.cost_usage
      WHERE billing_period = date_format(current_date, '%Y-%m')
      GROUP BY 1, 2, 3, 4, 5, 7
      ORDER BY unblended_cost DESC
    SQL
  }
}
resource "aws_athena_named_query" "monthly_account_service" {
  name = "Monthly unblended cost by account and service"
  workgroup = aws_athena_workgroup.hermes_analytics.id
  database = aws_glue_catalog_database.org_billing.name
  query = local.cost_queries.monthly_account_service
}
resource "aws_athena_named_query" "daily_current_month" {
  name = "Daily unblended cost for current billing month"
  workgroup = aws_athena_workgroup.hermes_analytics.id
  database = aws_glue_catalog_database.org_billing.name
  query = local.cost_queries.daily_current_month
}
resource "aws_athena_named_query" "usage_dimensions" {
  name = "Usage by account, service, usage type, operation and pricing unit"
  workgroup = aws_athena_workgroup.hermes_analytics.id
  database = aws_glue_catalog_database.org_billing.name
  query = local.cost_queries.usage_dimensions
}
