vault {
  address = "https://vault.home.arpa:8200"
}

exit_after_auth = false
pid_file = "/agent/run/agent.pid"

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

# --- coredns omada env ---
template {
  source      = "/agent/templates/coredns-omada.env.ctmpl"
  destination = "/agent/out/coredns-omada.env"
  perms       = "0640"
}
