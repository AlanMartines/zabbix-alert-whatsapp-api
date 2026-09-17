#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o WhatsApp via uazapiGO.
# Endpoint de mídia: POST {url}/send/media (header: token)
# Endpoint de texto: POST {url}/send/text  (header: token)
#

import base64
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.stderr.write("Erro: biblioteca 'requests' não encontrada. Execute: pip install requests\n")
    sys.exit(1)

# Configurações do gráfico e requisição
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "20"))
SEND_DELAY = int(os.environ.get("WA_SEND_DELAY", "500"))

MEDIA_MODE = os.environ.get("UAZ_MEDIA_MODE", "base64").strip().lower()
MEDIA_URL = os.environ.get("UAZ_MEDIA_URL", "").strip()


def log_err(msg):
    sys.stderr.write(f"[Zabbix-uazapi] {msg}\n")


def fail(msg):
    log_err(f"FATAL: {msg}")
    sys.exit(1)


def tls_option(env_name):
    val = os.environ.get(env_name, "true").strip()
    if val.lower() in ("false", "0", "no"):
        return False
    if val.lower() in ("true", "1", "yes", ""):
        return True
    return val


def parse_arguments():
    if len(sys.argv) != 10:
        fail(f"Parâmetros incorretos. Recebidos {len(sys.argv)-1}, esperados 9.")

    raw_item_id = sys.argv[4].strip()
    clean_item_id = raw_item_id if raw_item_id.isdigit() else None

    # Sanitização: números puros se não for identificador de grupo (@g.us)
    raw_to = sys.argv[7].strip()
    to_dest = raw_to if "@" in raw_to else re.sub(r"\D", "", raw_to)

    cfg = {
        "url_zbx": sys.argv[1].rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": clean_item_id,
        "url_api": sys.argv[5].rstrip("/"),
        "token": os.environ.get("UAZ_TOKEN") or sys.argv[6],
        "to": to_dest,
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }

    if not cfg["url_zbx"].startswith(("http://", "https://")):
        fail("URLZBX deve começar com 'http://' ou 'https://'.")
    if not cfg["user_zbx"]:
        fail("USERZBX não pode estar vazio.")
    if not cfg["pwd_zbx"]:
        fail("PWDZBX não pode estar vazio.")
    if not cfg["url_api"].startswith(("http://", "https://")):
        fail("URLAPI deve começar com 'http://' ou 'https://'.")
    if not cfg["token"]:
        fail("TOKEN não pode estar vazio.")
    if not cfg["to"]:
        fail("Destinatário (TO) não pode estar vazio.")

    if MEDIA_MODE == "url" and not MEDIA_URL:
        fail("UAZ_MEDIA_MODE='url' exige UAZ_MEDIA_URL preenchida.")

    return cfg


def fetch_graph(cfg, verify):
    """Autentica na UI do Zabbix 7 e obtém o gráfico."""
    if not cfg["item_id"]:
        return None

    session = requests.Session()
    login_url = f"{cfg['url_zbx']}/index.php"

    try:
        # GET inicial para carregar cookies de sessão do Zabbix 7.x
        session.get(login_url, verify=verify, timeout=HTTP_TIMEOUT)

        login_data = {
            "name": cfg["user_zbx"],
            "password": cfg["pwd_zbx"],
            "enter": "Sign in",
            "autologin": 1,
            "request": "",
        }
        session.post(login_url, data=login_data, verify=verify, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        log_err(f"Falha na conexão com Zabbix: {exc}")
        return None

    if "zbx_session" not in session.cookies:
        log_err("Não foi possível autenticar no Zabbix (cookie zbx_session ausente).")
        return None

    graph_url = (
        f"{cfg['url_zbx']}/chart.php?from={GRAPH_FROM}&to={GRAPH_TO}"
        f"&itemids[0]={cfg['item_id']}&type={GRAPH_TYPE}&profileIdx={GRAPH_PROFILE_IDX}"
        f"&width={GRAPH_WIDTH}&height={GRAPH_HEIGHT}"
    )

    try:
        res = session.get(graph_url, verify=verify, timeout=HTTP_TIMEOUT)
        if res.ok and res.content.startswith(b"\x89PNG"):
            return res.content
        log_err(f"chart.php não devolveu PNG válido (HTTP {res.status_code})")
    except Exception as exc:
        log_err(f"Erro ao baixar gráfico do item {cfg['item_id']}: {exc}")

    return None


def post_json(cfg, path, payload, verify):
    url = f"{cfg['url_api']}{path}"
    headers = {"Content-Type": "application/json", "token": cfg["token"]}
    return requests.post(url, json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT)


def send_text(cfg, verify):
    """Fallback garantido: envia somente o texto do alerta via POST /send/text."""
    payload = {
        "number": cfg["to"],
        "text": f"{cfg['subject']}\n\n{cfg['msg']}",
        "delay": SEND_DELAY,
    }
    try:
        res = post_json(cfg, "/send/text", payload, verify)
        if res.status_code in (200, 201):
            print("Mensagem de texto enviada com sucesso.")
            return True
        fail(f"Falha ao enviar texto na uazapi (HTTP {res.status_code}): {res.text[:300]}")
    except Exception as exc:
        fail(f"Erro de conexão com uazapi: {exc}")


def send_media(cfg, image_bytes, verify):
    """Envia gráfico e texto via POST /send/media com fallback automático para texto."""
    if MEDIA_MODE == "url":
        file_ref = MEDIA_URL
    else:
        file_ref = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "number": cfg["to"],
        "type": "image",
        "file": file_ref,
        "text": f"{cfg['subject']}\n\n{cfg['msg']}",
        "mimetype": "image/png",
        "delay": SEND_DELAY,
    }

    try:
        res = post_json(cfg, "/send/media", payload, verify)
        if res.status_code in (200, 201):
            print("Mensagem e gráfico enviados com sucesso.")
            return True
        log_err(f"uazapi recusou mídia (HTTP {res.status_code}). Acionando fallback para texto.")
    except Exception as exc:
        log_err(f"Erro ao enviar mídia: {exc}. Acionando fallback para texto.")

    return send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    zbx_verify = tls_option("ZBX_VERIFY_TLS")
    uaz_verify = tls_option("UAZ_VERIFY_TLS")

    image_bytes = None
    if cfg["item_id"]:
        image_bytes = fetch_graph(cfg, zbx_verify)

    if image_bytes:
        send_media(cfg, image_bytes, uaz_verify)
    else:
        send_text(cfg, uaz_verify)


if __name__ == "__main__":
    main()
