output "project_id" {
  description = "Verified existing Google project ID."
  value       = google_project.google_auth.project_id
}

output "project_number" {
  description = "Verified existing Google project number."
  value       = google_project.google_auth.number
}

output "project_name" {
  description = "Verified existing Google project display name."
  value       = google_project.google_auth.name
}
