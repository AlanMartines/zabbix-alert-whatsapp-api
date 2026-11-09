# Zabbix Alert Telegram

Media types e script de alerta para enviar notificações do Zabbix para o Telegram,
com os mesmos templates e o mesmo envio de gráfico das integrações de WhatsApp
deste repositório.

## Estrutura

```
telegram/
├── zbx_mediatypes/                     Webhook, mensagens sem emojis
├── zbx_mediatypes_use_emojis/          Webhook, mensagens com emojis
├── zbx_mediatypes_use_emojis_graphic/  Script, envia o gráfico do item
└── alertscripts/telegram-graph.py      Script usado pelo media type com gráfico
```

Escolha **uma** das três variantes. Os nomes dos media types são `Telegram Bot`,
`Telegram Bot (emojis)` e `Telegram Bot - Graphic`, para não colidir com o media
type `Telegram` que já vem no Zabbix.

## Diferenças em relação ao WhatsApp

| | WhatsApp | Telegram |
|---|---|---|
| Autenticação | depende do provedor | token do bot, que faz parte da URL (`/bot<token>/...`) |
| Destino (*Send to*) | número ou ID do grupo | `chat_id`, `@canal` ou `chat_id:thread_id` |
| Negrito | `*texto*` | os mesmos `*texto*` dos templates, convertidos para `<b>` |
| Limite de texto | — | 4096 caracteres por mensagem, 1024 na legenda da foto |
| Gráfico | base64 no JSON | upload `multipart/form-data` em `sendPhoto` |
| Limite de envio | — | HTTP 429 com `retry_after`; o script espera e tenta de novo |

Os templates foram mantidos iguais aos do WhatsApp. O envio escapa `&`, `<` e `>`
do texto e só depois converte `*negrito*` em `<b>negrito</b>`. Assim, um nome de
trigger como `CPU load > 5` não quebra a formatação. Se mesmo assim o Telegram
recusar a formatação (`can't parse entities`), a mensagem é reenviada como texto
puro em vez de ser perdida.

## 1. Criar o bot e descobrir o chat_id

1. No Telegram, fale com o [@BotFather](https://t.me/BotFather), envie `/newbot` e
   guarde o token (formato `123456789:AA...`).
2. Adicione o bot ao grupo ou canal de destino. Em canais, ele precisa ser
   administrador com permissão para publicar.
3. Envie qualquer mensagem no grupo (ou para o bot, no privado) e consulte:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   O `chat_id` está em `result[].message.chat.id`. Grupos e supergrupos têm IDs
   negativos (ex.: `-1001234567890`).

Formatos aceitos em *Send to*:

| Destino | Exemplo |
|---|---|
| Usuário (chat privado) | `123456789` |
| Grupo ou supergrupo | `-1001234567890` |
| Canal público | `@meucanal` |
| Tópico de um grupo fórum | `-1001234567890:42` (`chat_id:thread_id`) |

## 2. Importar o media type

No frontend: **Alerts → Media types → Import**, e selecione o `.yaml` desejado em
uma das três pastas.

### Webhooks (sem gráfico)

Edite o media type importado e preencha:

| Parâmetro | Valor |
|---|---|
| `Token` | token do bot |
| `Url` | `https://api.telegram.org` (troque só se usar um [Bot API server local](https://github.com/tdlib/telegram-bot-api)) |
| `ParseMode` | `HTML` (padrão) ou vazio para texto puro |
| `HTTPProxy` | opcional, ex.: `http://proxy:3128` |

## 3. Media type com gráfico

Instale a biblioteca `requests` e copie o script para o `AlertScriptsPath` do
servidor Zabbix:

```bash
sudo apt install -y python3-requests   # ou: pip install requests
sudo install -o zabbix -g zabbix -m 0750 telegram/alertscripts/telegram-graph.py /usr/lib/zabbix/alertscripts/
```

Argumentos (já configurados no media type):

```
telegram-graph.py URLZBX USERZBX PWDZBX ITEMIDZBX TOKEN TO SUBJECT MSG
```

Teste pela linha de comando antes de habilitar o media type (ele vem
`DISABLED`):

```bash
/usr/lib/zabbix/alertscripts/telegram-graph.py \
  https://zabbix.seudominio.com Admin senha 48061 \
  123456789:AA_SEU_TOKEN -1001234567890 'Teste' '*Host:* servidor01'
```

O script autentica no frontend do Zabbix, baixa o PNG do gráfico, encerra a
sessão e envia a foto com o texto como legenda. Comportamento em casos especiais:

- **texto maior que a legenda (1024):** envia a foto sem legenda e, em seguida, o
  texto completo como mensagem;
- **sem gráfico** (sem item, senha errada ou `chart.php` falhou): envia só o texto;
- **foto recusada pela API:** envia só o texto;
- **HTTP 429:** espera o `retry_after` informado (até 30s) e tenta mais uma vez.

O token nunca é escrito no log: ele aparece como `***` inclusive nas mensagens
de erro de conexão.

### Variáveis de ambiente

Além das variáveis comuns a todos os scripts (`ZBX_USER`, `ZBX_PASSWORD`,
`ZBX_VERIFY_TLS`, `ZBX_GRAPH_*`, `ZBX_HTTP_TIMEOUT` — veja o
[README principal](../README.md#segredos-por-variável-de-ambiente)):

| Variável | Padrão | Descrição |
|---|---|---|
| `TG_TOKEN` | — | token do bot; substitui o argumento `TOKEN` (deixe-o `''`) |
| `TG_API_URL` | `https://api.telegram.org` | URL da Bot API (ex.: servidor local) |
| `TG_PARSE_MODE` | `HTML` | `HTML` ou vazio para texto puro |
| `TG_VERIFY_TLS` | `true` | `true`, `false` ou caminho para o CA bundle |

Se o servidor Zabbix só sai para a internet por proxy, defina `HTTPS_PROXY` no
ambiente do serviço; a biblioteca `requests` usa essa variável automaticamente.
