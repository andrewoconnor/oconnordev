locals {
  google_openapi = {
    openapi = "3.0.3"
    info = {
      title       = "Google read-only"
      version     = "1.0.0"
      description = "Read-only subset of the Gmail API v1 and Google Calendar API v3 for the owner's account."
    }
    servers = [{ url = "https://www.googleapis.com" }]
    paths = {
      "/gmail/v1/users/me/labels" = {
        get = {
          operationId = "listLabels"
          summary     = "List the owner's Gmail labels, including system labels such as INBOX."
          responses   = local.google_json_response
        }
      }
      "/gmail/v1/users/me/messages" = {
        get = {
          operationId = "listMessages"
          summary     = "List Gmail message and thread IDs, newest first. Use getMessage to read one."
          parameters = [
            { name = "q", in = "query", description = "Gmail search query, for example \"from:alice newer_than:7d\"", schema = { type = "string" } },
            { name = "labelIds", in = "query", description = "Only messages with this label ID, for example INBOX", schema = { type = "string" } },
            { name = "maxResults", in = "query", description = "Maximum number of IDs to return, 1 to 100", schema = { type = "integer", minimum = 1, maximum = 100 } },
            { name = "pageToken", in = "query", description = "nextPageToken from the previous response", schema = { type = "string" } },
          ]
          responses = local.google_json_response
        }
      }
      "/gmail/v1/users/me/messages/{id}" = {
        get = {
          operationId = "getMessage"
          summary     = "Read one Gmail message. format=metadata returns headers and snippet only; format=full also returns the base64url-encoded body parts."
          parameters = [
            { name = "id", in = "path", required = true, description = "Message ID from listMessages", schema = { type = "string" } },
            { name = "format", in = "query", description = "metadata (default) or full", schema = { type = "string", enum = ["metadata", "full"], default = "metadata" } },
          ]
          responses = local.google_json_response
        }
      }
      "/calendar/v3/users/me/calendarList" = {
        get = {
          operationId = "listCalendars"
          summary     = "List the owner's Google calendars. Use the id with listEvents; the primary calendar's id is \"primary\"."
          parameters = [
            { name = "maxResults", in = "query", description = "Maximum calendars to return, 1 to 250", schema = { type = "integer", minimum = 1, maximum = 250 } },
            { name = "pageToken", in = "query", description = "nextPageToken from the previous response", schema = { type = "string" } },
          ]
          responses = local.google_json_response
        }
      }
      "/calendar/v3/calendars/{calendarId}/events" = {
        get = {
          operationId = "listEvents"
          summary     = "List events on one Google calendar. Set singleEvents=true and orderBy=startTime to expand recurring events in start order."
          parameters = [
            { name = "calendarId", in = "path", required = true, description = "Calendar id from listCalendars, or \"primary\"", schema = { type = "string" } },
            { name = "timeMin", in = "query", description = "Lower bound (exclusive) for an event's end time, RFC 3339 with offset, for example 2026-10-19T00:00:00-04:00", schema = { type = "string" } },
            { name = "timeMax", in = "query", description = "Upper bound (exclusive) for an event's start time, RFC 3339 with offset", schema = { type = "string" } },
            { name = "q", in = "query", description = "Free-text search in event fields", schema = { type = "string" } },
            { name = "singleEvents", in = "query", description = "Expand recurring events into instances", schema = { type = "boolean" } },
            { name = "orderBy", in = "query", description = "startTime (needs singleEvents=true) or updated", schema = { type = "string", enum = ["startTime", "updated"] } },
            { name = "maxResults", in = "query", description = "Maximum events to return, 1 to 250", schema = { type = "integer", minimum = 1, maximum = 250 } },
            { name = "pageToken", in = "query", description = "nextPageToken from the previous response", schema = { type = "string" } },
            { name = "timeZone", in = "query", description = "IANA time zone for the response, for example America/New_York", schema = { type = "string" } },
          ]
          responses = local.google_json_response
        }
      }
    }
  }
  google_json_response = {
    "200" = {
      description = "Success"
      content     = { "application/json" = { schema = { type = "object" } } }
    }
  }
}
