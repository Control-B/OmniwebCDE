terraform {
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.11"
    }
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.68"
    }
  }
}

data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

variable "region" {
  type        = string
  description = "DigitalOcean region slug"
  default     = "nyc3"
}

variable "size" {
  type        = string
  description = "DigitalOcean Droplet size slug"
  default     = "s-2vcpu-4gb"
}

resource "coder_agent" "main" {
  arch = "amd64"
  os   = "linux"
  dir  = "/workspace/project"

  startup_script = <<-EOT
    set -e
    git config --global init.defaultBranch main
    if ! command -v node >/dev/null; then
      curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
      sudo apt-get install -y nodejs
    fi
  EOT

  metadata {
    display_name = "CPU"
    key          = "cpu"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }
  metadata {
    display_name = "Memory"
    key          = "memory"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }
}

resource "coder_app" "web_ide" {
  agent_id     = coder_agent.main.id
  slug         = "code"
  display_name = "Browser IDE"
  icon         = "/icon/code.svg"
  url          = "http://localhost:13337/?folder=/workspace/project"
  subdomain    = true
  share        = "owner"

  healthcheck {
    url       = "http://localhost:13337/healthz"
    interval  = 10
    threshold = 6
  }
}

resource "digitalocean_volume" "workspace" {
  region                  = var.region
  name                    = "omniweb-${lower(data.coder_workspace.me.name)}"
  size                    = 25
  initial_filesystem_type = "ext4"
  description             = "Persistent Omniweb workspace data"
  tags                    = ["omniweb", "workspace-${data.coder_workspace.me.id}"]
}

resource "digitalocean_droplet" "workspace" {
  count      = data.coder_workspace.me.start_count
  image      = "ubuntu-24-04-x64"
  name       = "omniweb-${lower(data.coder_workspace.me.name)}"
  region     = var.region
  size       = var.size
  monitoring = true
  ipv6       = false
  tags       = ["omniweb", "workspace-${data.coder_workspace.me.id}"]

  # The Coder-generated init script contains only a workspace-scoped agent
  # credential. Provider credentials remain inside the Coder provisioner.
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    init_script = base64encode(coder_agent.main.init_script)
  })
}

resource "digitalocean_volume_attachment" "workspace" {
  count      = data.coder_workspace.me.start_count
  droplet_id = digitalocean_droplet.workspace[0].id
  volume_id  = digitalocean_volume.workspace.id
}

resource "digitalocean_firewall" "workspace" {
  count       = data.coder_workspace.me.start_count
  name        = "omniweb-${lower(data.coder_workspace.me.name)}"
  droplet_ids = [digitalocean_droplet.workspace[0].id]

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
