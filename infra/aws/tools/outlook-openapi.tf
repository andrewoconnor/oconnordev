locals {
  outlook_openapi = {
    openapi = "3.0.3"
    info = {
      title       = "Outlook read-only"
      version     = "1.0.0"
      description = "Read-only subset of Microsoft Graph mail and calendar for the owner's personal account. Uses the beta endpoint, where OData options need no $ prefix."
    }
    servers = [{ url = "https://graph.microsoft.com/beta" }]
    paths = {
      "/me/mailFolders" = {
        get = {
          operationId = "listMailFolders"
          summary     = "List the owner's top-level mail folders. Well-known folder names such as inbox also work as folder IDs."
          parameters = [
            { name = "top", in = "query", description = "Maximum folders to return, 1 to 100", schema = { type = "integer", minimum = 1, maximum = 100 } },
            { name = "skip", in = "query", description = "Number of folders to skip", schema = { type = "integer", minimum = 0 } },
          ]
          responses = local.graph_json_response
        }
      }
      "/me/mailFolders/{mailFolderId}/messages" = {
        get = {
          operationId = "listMessages"
          summary     = "List messages in one mail folder, newest first by default. Use select to keep responses small; search cannot be combined with orderby."
          parameters = [
            { name = "mailFolderId", in = "path", required = true, description = "Folder ID from listMailFolders, or a well-known name such as inbox", schema = { type = "string" } },
            { name = "top", in = "query", description = "Maximum messages to return, 1 to 50", schema = { type = "integer", minimum = 1, maximum = 50 } },
            { name = "skip", in = "query", description = "Number of messages to skip", schema = { type = "integer", minimum = 0 } },
            { name = "select", in = "query", description = "Comma-separated fields, for example subject,from,receivedDateTime,bodyPreview,isRead", schema = { type = "string" } },
            { name = "filter", in = "query", description = "OData filter, for example isRead eq false", schema = { type = "string" } },
            { name = "orderby", in = "query", description = "For example receivedDateTime desc", schema = { type = "string" } },
            { name = "search", in = "query", description = "Search text in double quotes, for example \"invoice\"", schema = { type = "string" } },
          ]
          responses = local.graph_json_response
        }
      }
      "/me/messages/{messageId}" = {
        get = {
          operationId = "getMessage"
          summary     = "Read one message. Use select to limit fields, for example subject,from,toRecipients,receivedDateTime,body."
          parameters = [
            { name = "messageId", in = "path", required = true, description = "Message ID from listMessages", schema = { type = "string" } },
            { name = "select", in = "query", description = "Comma-separated fields", schema = { type = "string" } },
          ]
          responses = local.graph_json_response
        }
      }
      "/me/calendars" = {
        get = {
          operationId = "listCalendars"
          summary     = "List the owner's Outlook calendars. Use the id with listEvents."
          parameters = [
            { name = "top", in = "query", description = "Maximum calendars to return, 1 to 100", schema = { type = "integer", minimum = 1, maximum = 100 } },
          ]
          responses = local.graph_json_response
        }
      }
      "/me/calendars/{calendarId}/calendarView" = {
        get = {
          operationId = "listEvents"
          summary     = "List event occurrences on one Outlook calendar between two times, with recurring events expanded."
          parameters = [
            { name = "calendarId", in = "path", required = true, description = "Calendar ID from listCalendars", schema = { type = "string" } },
            { name = "startDateTime", in = "query", required = true, description = "Range start, ISO 8601, for example 2026-10-19T00:00:00-04:00", schema = { type = "string" } },
            { name = "endDateTime", in = "query", required = true, description = "Range end, ISO 8601", schema = { type = "string" } },
            { name = "top", in = "query", description = "Maximum events to return, 1 to 100", schema = { type = "integer", minimum = 1, maximum = 100 } },
            { name = "select", in = "query", description = "Comma-separated fields, for example subject,start,end,location,isAllDay", schema = { type = "string" } },
            { name = "orderby", in = "query", description = "For example start/dateTime", schema = { type = "string" } },
          ]
          responses = local.graph_json_response
        }
      }
    }
  }
  graph_json_response = {
    "200" = {
      description = "Success"
      content     = { "application/json" = { schema = { type = "object" } } }
    }
  }
}
