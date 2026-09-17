#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o WhatsApp via Evolution Go.
#
# Referência da API:
#   https://docs.evolutionfoundation.com.br/evolution-go/send-a-media-message
#   POST {url}/send/media    header: apikey    body: {number, url, caption, ...}
#   https://docs.evolutionfoundation.com.br/evolution-go/send-a-text-message
#   POST {url}/send/text     header: apikey    body: {number, text, ...}
#
# Diferenças em relação à Evolution API:
#   - a instância NÃO vai no path; ela é identificada pelo token (apikey) usado;
#   - o campo da mídia chama-se `url` (e não `media`) e o tipo, `type` (e não
#     `mediatype`). Assim como na Evolution API, `url` aceita tanto uma URL
#     quanto o conteúdo em base64 — este script envia o PNG em base64.
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

# Configurações de gráfico e rede
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "15"))
SEND_DELAY = int(os.environ.get("WA_SEND_DELAY", "500"))

MEDIA_MODE = os.environ.get("EVOGO_MEDIA_MODE", "base64").strip().lower()
MEDIA_URL = os.environ.get("EVOGO_MEDIA_URL", "").strip()


def log_err(msg):
    sys.stderr.write(f"[Zabbix-WA-Go] {msg}\n")


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
    # Se vier macro não resolvida {ITEM.ID}, {ITEM.ID1} ou vazio, considera sem item
    clean_item_id = raw_item_id if raw_item_id.isdigit() else None

    # Sanitização do destinatário (remove caracteres não numéricos a não ser que seja grupo @g.us)
    raw_to = sys.argv[7].strip()
    to_dest = raw_to if "@" in raw_to else re.sub(r"\D", "", raw_to)

    return {
        "url_zbx": sys.argv[1].rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": clean_item_id,
        "url_api": sys.argv[5].rstrip("/"),
        "apikey": os.environ.get("EVOGO_APIKEY") or sys.argv[6],
        "to": to_dest,
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }


def fetch_graph(cfg, verify):
    """Autentica na UI do Zabbix 7.x e obtém o gráfico."""
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
        log_err(f"Falha na requisição de login ao Zabbix: {exc}")
        return None

    if "zbx_session" not in session.cookies:
        log_err("Não foi possível autenticar no Zabbix. Verifique usuário e senha.")
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
    headers = {"Content-Type": "application/json", "apikey": cfg["apikey"]}
    return requests.post(url, json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT)


def send_text(cfg, verify):
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
        fail(f"Falha ao enviar texto na Evolution Go (HTTP {res.status_code}): {res.text[:300]}")
    except Exception as exc:
        fail(f"Erro de conexão com Evolution Go: {exc}")


def send_media(cfg, image_bytes, verify):
    if MEDIA_MODE == "url":
        media_ref = MEDIA_URL
    else:
        media_ref = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "number": cfg["to"],
        "url": media_ref,
        "type": "image",
        "caption": f"{cfg['subject']}\n\n{cfg['msg']}",
        "filename": f"graph_{cfg['item_id']}.png",
        "delay": SEND_DELAY,
    }

    try:
        res = post_json(cfg, "/send/media", payload, verify)
        if res.status_code in (200, 201):
            print("Gráfico e mensagem enviados com sucesso.")
            return True
        log_err(f"Evolution Go recusou mídia (HTTP {res.status_code}). Tentando fallback para texto.")
    except Exception as exc:
        log_err(f"Erro ao disparar mídia: {exc}. Tentando fallback para texto.")

    # Fallback garantido
    return send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    zbx_verify = tls_option("ZBX_VERIFY_TLS")
    evogo_verify = tls_option("EVOGO_VERIFY_TLS")

    image_bytes = None
    if cfg["item_id"]:
        image_bytes = fetch_graph(cfg, zbx_verify)

    if image_bytes:
        send_media(cfg, image_bytes, evogo_verify)
    else:
        send_text(cfg, evogo_verify)


if __name__ == "__main__":
    main()
