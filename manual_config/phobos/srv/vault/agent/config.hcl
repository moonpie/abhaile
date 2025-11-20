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

# --- File ready flag ---
template {
  source      = "/agent/templates/ready.ctmpl"
  destination = "/agent/out/.ready"
  perms       = "0640"
}

# --- caddy dns desec env ---
template {
  source      = "/agent/templates/caddy-dns-desec.env.ctmpl"
  destination = "/agent/out/caddy-dns-desec.env"
  perms       = "0640"
}

# --- coredns omada env ---
template {
  source      = "/agent/templates/coredns-omada.env.ctmpl"
  destination = "/agent/out/coredns-omada.env"
  perms       = "0640"
}

# --- ddclient.conf ---
template {
  source      = "/agent/templates/ddclient.conf.ctmpl"
  destination = "/agent/out/ddclient.conf"
  perms       = "0640"
}

# --- Authelia secrets ---
template {
  source      = "/agent/templates/authelia.configuration.yml.ctmpl"
  destination = "/agent/out/authelia.configuration.yml"
  perms       = "0640"
}

# --- Redis secrets ---
template {
  source      = "/agent/templates/authelia-redis.conf.ctmpl"
  destination = "/agent/out/authelia-redis.conf"
  perms       = "0640"
}
