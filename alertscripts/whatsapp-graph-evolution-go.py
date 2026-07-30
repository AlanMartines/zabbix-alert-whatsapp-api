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
import sys

try:
    import requests
except ImportError:
    sys.stderr.write(
        "Erro: a biblioteca 'requests' não está instalada.\n"
        "Instale no deploy com: pip install requests\n"
    )
    sys.exit(1)


# --- Configuração do gráfico (ajuste conforme necessário) --------------------
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")   # Tempo inicial
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")          # Tempo final
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")   # Largura do gráfico
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")  # Altura do gráfico
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")        # 0=linha simples, 1=empilhado
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "30"))
SEND_DELAY = int(os.environ.get("WA_SEND_DELAY", "1200"))

# 'base64' (padrão) envia o PNG codificado no campo `url`.
# 'url' usa EVOGO_MEDIA_URL como URL pública do PNG, sem embutir a imagem.
MEDIA_MODE = os.environ.get("EVOGO_MEDIA_MODE", "base64").strip().lower()
MEDIA_URL = os.environ.get("EVOGO_MEDIA_URL", "").strip()

USAGE = """\
Usage: {prog} {{URLZBX}} {{USERZBX}} {{PWDZBX}} {{ITEMIDZBX}} {{URLAPI}} {{APIKEY}} {{TO}} {{SUBJECT}} {{MSG}}

A instância do Evolution Go é determinada pelo token informado em APIKEY
(token global ou o token específico da instância, obtido em GET /instance/all).

Os segredos podem (e devem) vir do ambiente, deixando o argumento vazio (''):
  ZBX_USER      usuário do Zabbix         (substitui USERZBX)
  ZBX_PASSWORD  senha do Zabbix           (substitui PWDZBX)
  EVOGO_APIKEY  token do Evolution Go     (substitui APIKEY)

Outras variáveis opcionais:
  ZBX_VERIFY_TLS    'true' (padrão), 'false' ou caminho para o CA bundle
  EVOGO_VERIFY_TLS  idem, para a chamada ao Evolution Go
  EVOGO_MEDIA_MODE  'base64' (padrão) ou 'url'
  EVOGO_MEDIA_URL   URL pública do PNG, obrigatória quando MODE='url'
  ZBX_GRAPH_FROM    janela do gráfico (padrão: now-6h)
  ZBX_HTTP_TIMEOUT  timeout em segundos (padrão: 30)

Example:
========
{prog} https://zabbix.seudominio.com Admin zabbix 48061 https://go.seudominio.com KHKHKHGKGJ 550000000000 'Subject' 'Msg from to WhatsApp'
"""


def fail(msg):
    """Encerra com status 1 para que o Zabbix registre a falha do alerta."""
    sys.stderr.write("Erro: {}\n".format(msg))
    sys.exit(1)


def tls_option(env_name):
    """Traduz a variável de ambiente para o parâmetro `verify` do requests.

    Aceita 'false' (desliga a validação), 'true' (padrão) ou um caminho de CA.
    """
    value = os.environ.get(env_name, "true").strip()
    if value.lower() in ("false", "0", "no"):
        sys.stderr.write(
            "Aviso: validação de certificado desativada em {} — o tráfego "
            "(inclusive credenciais) fica sujeito a interceptação.\n".format(env_name)
        )
        return False
    if value.lower() in ("true", "1", "yes", ""):
        return True
    return value  # caminho para o CA bundle


def parse_arguments():
    expected_args = 10
    if len(sys.argv) != expected_args:
        sys.stderr.write("Erro: número incorreto de argumentos fornecidos.\n\n")
        sys.stderr.write(USAGE.format(prog=sys.argv[0]))
        sys.exit(1)

    cfg = {
        "url_zbx": sys.argv[1].rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": sys.argv[4],
        "url_api": sys.argv[5].rstrip("/"),
        "apikey": os.environ.get("EVOGO_APIKEY") or sys.argv[6],
        "to": sys.argv[7],
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }

    if not cfg["url_zbx"].startswith(("http://", "https://")):
        fail("URLZBX deve começar com 'http://' ou 'https://'.")
    if not cfg["user_zbx"]:
        fail("USERZBX não pode estar vazio (nem o argumento nem ZBX_USER).")
    if not cfg["pwd_zbx"]:
        fail("PWDZBX não pode estar vazio (nem o argumento nem ZBX_PASSWORD).")
    if not cfg["item_id"].isdigit():
        fail("ITEMIDZBX deve ser um número.")
    if not cfg["url_api"].startswith(("http://", "https://")):
        fail("URLAPI deve começar com 'http://' ou 'https://'.")
    if not cfg["apikey"]:
        fail("APIKEY não pode estar vazio (nem o argumento nem EVOGO_APIKEY).")
    if not cfg["to"]:
        fail("TO não pode estar vazio.")
    if not cfg["subject"]:
        fail("SUBJECT não pode estar vazio.")
    if not cfg["msg"]:
        fail("MSG não pode estar vazio.")

    if MEDIA_MODE not in ("base64", "url"):
        fail("EVOGO_MEDIA_MODE deve ser 'base64' ou 'url'.")
    if MEDIA_MODE == "url" and not MEDIA_URL:
        fail("EVOGO_MEDIA_MODE='url' exige EVOGO_MEDIA_URL preenchida.")

    return cfg


def fetch_graph(cfg, verify):
    """Autentica no frontend do Zabbix e baixa o PNG do gráfico do item.

    O chart.php é um endpoint do frontend e exige cookie de sessão — o token da
    API JSON-RPC não serve aqui, por isso o login é feito via formulário.
    """
    session = requests.Session()
    login_url = "{}/index.php".format(cfg["url_zbx"])

    login_data = {
        "name": cfg["user_zbx"],
        "password": cfg["pwd_zbx"],
        "enter": "Sign in",
        "autologin": 1,
        "request": "",
    }

    try:
        session.post(login_url, data=login_data, verify=verify, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        fail("falha ao conectar no Zabbix: {}".format(exc))

    # Detecta o sucesso pelo cookie de sessão, e não pelo texto da página, que
    # muda conforme o idioma do frontend.
    if "zbx_session" not in session.cookies:
        fail("falha no login do Zabbix — verifique usuário, senha e permissões.")

    graph_url = (
        "{base}/chart.php?from={_from}&to={_to}&itemids[0]={item}"
        "&type={type}&profileIdx={profile}&width={width}&height={height}"
    ).format(
        base=cfg["url_zbx"],
        _from=GRAPH_FROM,
        _to=GRAPH_TO,
        item=cfg["item_id"],
        type=GRAPH_TYPE,
        profile=GRAPH_PROFILE_IDX,
        width=GRAPH_WIDTH,
        height=GRAPH_HEIGHT,
    )

    try:
        response = session.get(graph_url, verify=verify, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        fail("falha ao obter o gráfico: {}".format(exc))

    if not response.ok:
        fail("falha ao obter o gráfico (HTTP {}).".format(response.status_code))

    # Sessão expirada devolve HTML com HTTP 200; o conteúdo precisa ser um PNG.
    if not response.content.startswith(b"\x89PNG"):
        fail(
            "o Zabbix não retornou uma imagem PNG (content-type: {}). "
            "Confira o ITEMID e as permissões do usuário.".format(
                response.headers.get("Content-Type", "desconhecido")
            )
        )

    return response.content


def post_json(cfg, path, payload, verify):
    """POST autenticado no Evolution Go. Devolve o objeto response."""
    url = "{}{}".format(cfg["url_api"], path)
    headers = {"Content-Type": "application/json", "apikey": cfg["apikey"]}

    try:
        return requests.post(
            url, json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT
        )
    except requests.RequestException as exc:
        fail("falha ao conectar no Evolution Go: {}".format(exc))


def send_text(cfg, verify):
    """Fallback: envia somente o texto do alerta via POST /send/text."""
    payload = {
        "number": cfg["to"],
        "text": "{}\n{}".format(cfg["subject"], cfg["msg"]),
        "delay": SEND_DELAY,
    }

    response = post_json(cfg, "/send/text", payload, verify)
    if response.status_code not in (200, 201):
        fail(
            "falha ao enviar a mensagem de texto (HTTP {}): {}".format(
                response.status_code, response.text[:500]
            )
        )

    print("Mensagem enviada sem o gráfico")


def send_media(cfg, image_bytes, verify):
    """Envia a imagem com legenda via POST /send/media.

    O campo `url` aceita uma URL ou o conteúdo em base64; por padrão embutimos
    o PNG, ou usamos a URL pública configurada em EVOGO_MEDIA_URL.
    """
    if MEDIA_MODE == "url":
        media_ref = MEDIA_URL
    else:
        media_ref = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "number": cfg["to"],
        "url": media_ref,
        "type": "image",
        "caption": "{}\n{}".format(cfg["subject"], cfg["msg"]),
        "filename": "graph_zabbix_{}.png".format(cfg["item_id"]),
        "delay": SEND_DELAY,
    }

    response = post_json(cfg, "/send/media", payload, verify)

    if response.status_code in (200, 201):
        print("Mensagem e gráfico enviados com sucesso")
        return

    # Se a mídia foi recusada, o alerta ainda precisa chegar: cai para texto.
    sys.stderr.write(
        "Aviso: falha ao enviar o gráfico (HTTP {}): {}\n"
        "Reenviando apenas o texto do alerta.\n".format(
            response.status_code, response.text[:500]
        )
    )
    send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    evogo_verify = tls_option("EVOGO_VERIFY_TLS")
    image_bytes = fetch_graph(cfg, tls_option("ZBX_VERIFY_TLS"))
    send_media(cfg, image_bytes, evogo_verify)


if __name__ == "__main__":
    main()
