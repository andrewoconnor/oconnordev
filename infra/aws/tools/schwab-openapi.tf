locals {
  schwab_openapi = {
    openapi = "3.0.3"
    info = {
      title       = "Schwab read-only"
      version     = "1.0.0"
      description = "Read-only subset of the Schwab Trader API: accounts, positions and market data. Order endpoints are not included. Calls go through hermes-schwab-proxy, which forwards GETs to api.schwabapi.com without the content-type header that Schwab rejects."
    }
    servers = [{ url = trimsuffix(aws_lambda_function_url.schwab_proxy.function_url, "/") }]
    paths = {
      "/trader/v1/accounts/accountNumbers" = {
        get = {
          operationId = "getAccountNumbers"
          summary     = "List the owner's account numbers with their hashValue. Use hashValue as accountHash in getAccount."
          responses   = local.schwab_json_response
        }
      }
      "/trader/v1/accounts" = {
        get = {
          operationId = "listAccounts"
          summary     = "List the owner's accounts with balances. Set fields=positions to include positions."
          parameters = [
            { name = "fields", in = "query", description = "positions to include positions", schema = { type = "string", enum = ["positions"] } },
          ]
          responses = local.schwab_json_response
        }
      }
      "/trader/v1/accounts/{accountHash}" = {
        get = {
          operationId = "getAccount"
          summary     = "Read one account's balances. Set fields=positions to include positions."
          parameters = [
            { name = "accountHash", in = "path", required = true, description = "hashValue from getAccountNumbers, not the plain account number", schema = { type = "string" } },
            { name = "fields", in = "query", description = "positions to include positions", schema = { type = "string", enum = ["positions"] } },
          ]
          responses = local.schwab_json_response
        }
      }
      "/marketdata/v1/quotes" = {
        get = {
          operationId = "getQuotes"
          summary     = "Get quotes for one or more symbols."
          parameters = [
            { name = "symbols", in = "query", required = true, description = "Comma-separated symbols, for example AAPL,MSFT,$SPX", schema = { type = "string" } },
            { name = "fields", in = "query", description = "Comma-separated: quote, fundamental, extended, reference, regular. Default all.", schema = { type = "string" } },
            { name = "indicative", in = "query", description = "Include indicative quotes for ETFs", schema = { type = "boolean" } },
          ]
          responses = local.schwab_json_response
        }
      }
      "/marketdata/v1/pricehistory" = {
        get = {
          operationId = "getPriceHistory"
          summary     = "Get price candles for one symbol. Dates are epoch milliseconds."
          parameters = [
            { name = "symbol", in = "query", required = true, description = "Symbol, for example AAPL", schema = { type = "string" } },
            { name = "periodType", in = "query", description = "day, month, year or ytd", schema = { type = "string", enum = ["day", "month", "year", "ytd"] } },
            { name = "period", in = "query", description = "Number of periods", schema = { type = "integer", minimum = 1 } },
            { name = "frequencyType", in = "query", description = "minute, daily, weekly or monthly", schema = { type = "string", enum = ["minute", "daily", "weekly", "monthly"] } },
            { name = "frequency", in = "query", description = "Candle size in frequencyType units", schema = { type = "integer", minimum = 1 } },
            { name = "startDate", in = "query", description = "Start, epoch milliseconds", schema = { type = "integer" } },
            { name = "endDate", in = "query", description = "End, epoch milliseconds", schema = { type = "integer" } },
            { name = "needExtendedHoursData", in = "query", description = "Include extended hours", schema = { type = "boolean" } },
            { name = "needPreviousClose", in = "query", description = "Include the previous close", schema = { type = "boolean" } },
          ]
          responses = local.schwab_json_response
        }
      }
      "/marketdata/v1/markets" = {
        get = {
          operationId = "getMarketHours"
          summary     = "Get market hours for one or more markets."
          parameters = [
            { name = "markets", in = "query", required = true, description = "Comma-separated: equity, option, bond, future, forex", schema = { type = "string" } },
            { name = "date", in = "query", description = "Date as YYYY-MM-DD, default today", schema = { type = "string" } },
          ]
          responses = local.schwab_json_response
        }
      }
      "/marketdata/v1/instruments" = {
        get = {
          operationId = "searchInstruments"
          summary     = "Look up instruments by symbol or description."
          parameters = [
            { name = "symbol", in = "query", required = true, description = "Symbol or search text", schema = { type = "string" } },
            { name = "projection", in = "query", required = true, description = "Search type", schema = { type = "string", enum = ["symbol-search", "symbol-regex", "desc-search", "desc-regex", "search", "fundamental"] } },
          ]
          responses = local.schwab_json_response
        }
      }
    }
  }
  schwab_json_response = {
    "200" = {
      description = "Success"
      content     = { "application/json" = { schema = { type = "object" } } }
    }
  }
}
