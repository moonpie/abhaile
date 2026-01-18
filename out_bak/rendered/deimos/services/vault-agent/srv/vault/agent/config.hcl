exit_after_auth = false
pid_file = "/agent/run/agent.pid"

vault {
  address = "http://172.20.20.204:8200"
}

auto_auth {
  method "token_file" {
    config = {
      token_file_path = "/agent/token"
    }
  }
  sink "file" {
    config = {
      path = "/agent/run/vault-agent-token"
      mode = 0600
    }
  }
}

# --- Service-collected templates ---
template {
  source      = "/agent/templates/coredns-omada.env.ctmpl"
  destination = "/agent/out/coredns-omada.env"
  perms       = "0640"
}
template {
  source      = "/agent/templates/ready.ctmpl"
  destination = "/agent/out/.ready"
  perms       = "0640"
}
