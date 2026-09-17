#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o WhatsApp via ConnectZap API.
#

import base64
import os
import sys

try:
    import requests
except ImportError:
    sys.stderr.write("Erro: biblioteca 'requests' não instalada. Execute: pip install requests\n")
    sys.exit(1)

# Configurações de gráfico e requisição
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "20"))


def log_err(msg):
    sys.stderr.write(f"[ConnectZap] {msg}\n")


def fail(msg):
    log_err(f"FATAL: {msg}")
    sys.exit(1)


def parse_arguments():
    if len(sys.argv) != 10:
        fail(f"Parâmetros incorretos. Recebidos {len(sys.argv)-1}, esperados 9.")

    raw_item_id = sys.argv[4].strip()
    clean_item_id = raw_item_id if raw_item_id.isdigit() else None

    cfg = {
        "url_zbx": sys.argv[1].rstrip("/"),
        "user_zbx": sys.argv[2],
        "pwd_zbx": sys.argv[3],
        "item_id": clean_item_id,
        "url_api": sys.argv[5].rstrip("/"),
        "token": sys.argv[6],
        "to": sys.argv[7].strip(),
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }

    if not cfg["url_zbx"].startswith(("http://", "https://")):
        fail("URLZBX deve começar com 'http://' ou 'https://'.")
    if not cfg["user_zbx"] or not cfg["pwd_zbx"]:
        fail("Credenciais do Zabbix não podem estar vazias.")
    if not cfg["url_api"].startswith(("http://", "https://")):
        fail("URLAPI deve começar com 'http://' ou 'https://'.")
    if not cfg["token"]:
        fail("TOKEN não pode estar vazio.")
    if not cfg["to"]:
        fail("Destinatário (TO) não pode estar vazio.")

    return cfg


def fetch_graph(cfg):
    """Autentica na UI do Zabbix 7.x e extrai o PNG do gráfico."""
    if not cfg["item_id"]:
        return None

    session = requests.Session()
    login_url = f"{cfg['url_zbx']}/index.php"

    try:
        # GET inicial para carregar cookies de sessão do Zabbix 7.x
        session.get(login_url, verify=False, timeout=HTTP_TIMEOUT)

        login_data = {
            "name": cfg["user_zbx"],
            "password": cfg["pwd_zbx"],
            "enter": "Sign in",
            "autologin": 1,
            "request": "",
        }
        session.post(login_url, data=login_data, verify=False, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        log_err(f"Falha de conexão com Zabbix: {exc}")
        return None

    if "zbx_session" not in session.cookies:
        log_err("Falha na autenticação do Zabbix (cookie zbx_session ausente).")
        return None

    graph_url = (
        f"{cfg['url_zbx']}/chart.php?from={GRAPH_FROM}&to={GRAPH_TO}"
        f"&itemids[0]={cfg['item_id']}&type={GRAPH_TYPE}&profileIdx={GRAPH_PROFILE_IDX}"
        f"&width={GRAPH_WIDTH}&height={GRAPH_HEIGHT}"
    )

    try:
        res = session.get(graph_url, verify=False, timeout=HTTP_TIMEOUT)
        if res.ok and res.content.startswith(b"\x89PNG"):
            return res.content
        log_err(f"chart.php não devolveu PNG válido (HTTP {res.status_code})")
    except Exception as exc:
        log_err(f"Erro ao obter PNG do item {cfg['item_id']}: {exc}")

    return None


def send_text(cfg):
    """Fallback: envia mensagem de texto no grupo."""
    url = f"{cfg['url_api']}/sistema/sendTextGrupo"
    payload = {
        "SessionName": cfg["token"],
        "groupId": cfg["to"],
        "text": f"{cfg['subject']}\n\n{cfg['msg']}",
    }
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, verify=False, timeout=HTTP_TIMEOUT)
        if res.status_code in (200, 201):
            print("Mensagem de texto enviada com sucesso no grupo.")
            return True
        fail(f"Falha no envio de texto (HTTP {res.status_code}): {res.text[:300]}")
    except Exception as exc:
        fail(f"Erro ao conectar na ConnectZap: {exc}")


def send_media(cfg, image_bytes):
    """Envia gráfico e legenda com fallback automático para texto."""
    url = f"{cfg['url_api']}/sistema/sendImageBase64Grupo"
    payload = {
        "SessionName": cfg["token"],
        "groupId": cfg["to"],
        "base64": base64.b64encode(image_bytes).decode("utf-8"),
        "originalname": f"graph_zabbix_{cfg['item_id']}.png",
        "caption": f"{cfg['subject']}\n\n{cfg['msg']}",
    }
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, verify=False, timeout=HTTP_TIMEOUT)
        if res.status_code in (200, 201):
            print("Gráfico e mensagem enviados com sucesso no grupo.")
            return True
        log_err(f"Falha no envio de mídia (HTTP {res.status_code}). Acionando fallback para texto.")
    except Exception as exc:
        log_err(f"Erro na requisição da imagem: {exc}. Acionando fallback para texto.")

    return send_text(cfg)


def main():
    cfg = parse_arguments()
    image_bytes = None

    if cfg["item_id"]:
        image_bytes = fetch_graph(cfg)

    if image_bytes:
        send_media(cfg, image_bytes)
    else:
        send_text(cfg)


if __name__ == "__main__":
    main()
