/**
 * Meta-Agent Terraform Configuration for Google Cloud Platform
 *
 * This Terraform configuration deploys the Meta-Agent application to Google Cloud Platform
 * using Cloud Run for the application, Cloud SQL for the database, and Secret Manager for secrets.
 */

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 4.0"
    }
  }
  required_version = ">= 1.0.0"
}

# Variables
variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "The GCP zone to deploy resources"
  type        = string
  default     = "us-central1-a"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "meta-agent"
}

variable "container_image" {
  description = "Container image to deploy (e.g., gcr.io/project-id/meta-agent:latest)"
  type        = string
}

variable "env_vars" {
  description = "Environment variables for the application"
  type        = map(string)
  default     = {}
}

variable "db_tier" {
  description = "The machine type for the database instance"
  type        = string
  default     = "db-f1-micro"
}

variable "memory_limit" {
  description = "Memory limit for Cloud Run service"
  type        = string
  default     = "1Gi"
}

variable "cpu_limit" {
  description = "CPU limit for Cloud Run service"
  type        = string
  default     = "1"
}

variable "min_instances" {
  description = "Minimum number of instances"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of instances"
  type        = number
  default     = 10
}

# Provider configuration
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# Enable required APIs
resource "google_project_service" "required_services" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "containerregistry.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "vpcaccess.googleapis.com"
  ])
  
  service = each.key
  disable_on_destroy = false
}

# Create a VPC network
resource "google_compute_network" "vpc_network" {
  name                    = "${var.app_name}-network"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required_services]
}

# Create a subnet
resource "google_compute_subnetwork" "subnet" {
  name          = "${var.app_name}-subnet"
  ip_cidr_range = "10.0.0.0/24"
  network       = google_compute_network.vpc_network.id
  region        = var.region
}

# Create a Serverless VPC Access connector
resource "google_vpc_access_connector" "connector" {
  name          = "${var.app_name}-vpc-connector"
  region        = var.region
  ip_cidr_range = "10.8.0.0/28"
  network       = google_compute_network.vpc_network.name
  depends_on    = [google_project_service.required_services]
}

# Create a Cloud SQL instance
resource "google_sql_database_instance" "instance" {
  name             = "${var.app_name}-db-instance"
  database_version = "POSTGRES_13"
  region           = var.region
  
  settings {
    tier = var.db_tier
    
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc_network.id
    }
  }
  
  deletion_protection = false
  depends_on          = [google_project_service.required_services]
}

# Create a database
resource "google_sql_database" "database" {
  name     = var.app_name
  instance = google_sql_database_instance.instance.name
}

# Create a database user
resource "google_sql_user" "user" {
  name     = "${var.app_name}-user"
  instance = google_sql_database_instance.instance.name
  password = random_password.db_password.result
}

# Generate a random password for the database
resource "random_password" "db_password" {
  length           = 16
  special          = true
  override_special = "_%@"
}

# Store the database password in Secret Manager
resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.app_name}-db-password"
  
  replication {
    automatic = true
  }
  
  depends_on = [google_project_service.required_services]
}

resource "google_secret_manager_secret_version" "db_password_version" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

# Create a service account for the Cloud Run service
resource "google_service_account" "service_account" {
  account_id   = "${var.app_name}-sa"
  display_name = "Service Account for ${var.app_name}"
}

# Grant the service account access to Secret Manager
resource "google_secret_manager_secret_iam_member" "secret_access" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service_account.email}"
}

# Deploy the application to Cloud Run
resource "google_cloud_run_service" "service" {
  name     = var.app_name
  location = var.region
  
  template {
    spec {
      containers {
        image = var.container_image
        
        resources {
          limits = {
            memory = var.memory_limit
            cpu    = var.cpu_limit
          }
        }
        
        # Environment variables
        dynamic "env" {
          for_each = var.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }
        
        # Add database connection environment variable
        env {
          name  = "META_AGENT_DB_CONNECTION_STRING"
          value = "postgresql://${google_sql_user.user.name}:${random_password.db_password.result}@${google_sql_database_instance.instance.private_ip_address}:5432/${google_sql_database.database.name}"
        }
      }
      
      service_account_name = google_service_account.service_account.email
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale"      = var.min_instances
        "autoscaling.knative.dev/maxScale"      = var.max_instances
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.connector.name
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }
  }
  
  traffic {
    percent         = 100
    latest_revision = true
  }
  
  depends_on = [
    google_project_service.required_services,
    google_sql_database.database,
    google_sql_user.user,
    google_vpc_access_connector.connector
  ]
}

# Allow unauthenticated access to the Cloud Run service
resource "google_cloud_run_service_iam_member" "public_access" {
  service  = google_cloud_run_service.service.name
  location = google_cloud_run_service.service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Outputs
output "service_url" {
  value       = google_cloud_run_service.service.status[0].url
  description = "The URL of the deployed service"
}

output "db_instance" {
  value       = google_sql_database_instance.instance.name
  description = "The name of the database instance"
}

output "db_connection" {
  value       = "postgresql://${google_sql_user.user.name}:[PASSWORD]@${google_sql_database_instance.instance.private_ip_address}:5432/${google_sql_database.database.name}"
  description = "The database connection string (password redacted)"
  sensitive   = false
}
