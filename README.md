# WhatsApp Marketing Nova Uniao

Automacao para disparo controlado de mensagens via WhatsApp usando Evolution API e leads do Supabase.

## Estado Atual

- Ambiente virtual criado em `.venv`.
- Dependencias instaladas via `requirements.txt`.
- Variaveis locais configuradas em `.env`.
- Base de origem: `mkt_novauniao.whatsapp_mkt`.
- Coluna `lote` criada e preenchida.
- Campanhas extraidas de `campanhas/Campanhas.docx`.
- Templates estruturados em `campanhas/campanhas_extraidas.json`.
- Imagens de campanha organizadas em `campanhas/imagens/`.
- Campanha 1 configurada com `campanhas/imagens/Campanha 1.png`.
- Saudacao personalizada com `{{decisor}}`.
- Preview automatico de link desativado na Evolution API com `linkPreview: false`.
- Campanhas com `image_path` sao enviadas pela Evolution API como `sendMedia`
  com a mensagem no campo `caption`.
- Fila ativa de disparo em Redis.
- Supabase usado para leads, campanhas, opt-outs e historico/eventos.
- Agendamento automatico pela planilha Google Sheets `Cronograma Whatsapp MKT`,
  aba `Agenda Whatsapp`.
- Mensagens ainda sem disparo real.

## Lotes

```text
lote1: 70 leads
lote2: 70 leads
lote3: 69 leads
lote4: 69 leads
lote5: 69 leads
```

## Tabelas Operacionais

Criadas no schema `mkt_novauniao`:

```text
whatsapp_campaigns
whatsapp_message_events
whatsapp_opt_outs
```

A fila ativa nao fica no Supabase. Ela fica no Redis, usando chaves com o prefixo configurado em `REDIS_QUEUE_PREFIX`.

## Agendamento por Planilha

A fonte de verdade do agendamento passa a ser a planilha Google Sheets
`Cronograma Whatsapp MKT`, aba `Agenda Whatsapp`. A service account precisa ter
acesso a essa planilha.

A aba deve ter estas colunas:

```text
Data | Dia | Janela | Horario inicio | Campanha | Lote | Qtd envios | Status | Observacoes
```

Colunas usadas pelo worker:

```text
Data
Horario inicio
Campanha
Lote
Qtd envios
Status
```

`Dia`, `Janela` e `Observacoes` sao informativas. Linhas com `Status` igual a
`Cancelada`, `Pausada` ou `Ignorar` nao sao processadas. `Agendada` e vazio sao
considerados ativos.

O worker roda a cada `WORKER_INTERVAL_SECONDS`, le a planilha no timezone
`America/Sao_Paulo`, enfileira as linhas vencidas no Redis e em seguida dispara
a fila. Com `WORKER_BATCH_SIZE=1`, ele envia no maximo uma mensagem por ciclo.

Exemplo de agenda:

```text
Campanha 1 | lote1 | 12/08/2026 | 10:00 | 35 mensagens
Campanha 1 | lote1 | 12/08/2026 | 14:00 | 35 mensagens
Campanha 2 | lote2 | 13/08/2026 | 10:00 | 35 mensagens
Campanha 2 | lote2 | 13/08/2026 | 14:00 | 35 mensagens
```

Cada linha cria/atualiza a campanha no Supabase e enfileira a proxima fatia de
leads daquele lote, ignorando leads que ja tenham evento `queued` ou `sent` para
a mesma campanha. Isso evita repetir os mesmos contatos quando a campanha tem
janela de manha e tarde.

Variaveis do agendamento:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=mkt-novauniao-d64a259b4a40.json
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SERVICE_ACCOUNT_JSON_BASE64=
WHATSAPP_SCHEDULE_ENABLED=true
WHATSAPP_SCHEDULE_DRY_RUN=false
WHATSAPP_SCHEDULE_LIMIT=
WHATSAPP_SCHEDULE_SPREADSHEET_NAME=Cronograma Whatsapp MKT
WHATSAPP_SCHEDULE_SPREADSHEET_ID=
WHATSAPP_SCHEDULE_SHEET_NAME=Agenda Whatsapp
```

Em producao, prefira configurar `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` como secret
em vez de copiar o arquivo JSON da service account para a imagem Docker.

Rodar manualmente o agendamento da planilha:

```powershell
python scripts\run_scheduled_campaign.py
python scripts\run_scheduled_campaign.py --run-date 2026-08-12
python scripts\run_scheduled_campaign.py --run-date 2026-08-12 --run-time 10:00 --dry-run
```

## Como Usar

Ativar ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar dependencias:

```powershell
pip install -r requirements.txt
```

Conferir leads por lote:

```powershell
python scripts\sync_leads.py
python scripts\sync_leads.py --lote lote1
```

Criar ou atualizar tabelas operacionais:

```powershell
python scripts\create_operational_tables.py
```

Enviar mensagem de teste:

```powershell
python scripts\test_send.py --phone 5511999999999 --message "Ola! Veja esse post: https://instagram.com/p/Dbq1A8roEjQ/"
```

Use `--link-preview` apenas se quiser testar explicitamente o card automatico
do WhatsApp.

Enviar preview de campanha para o numero interno:

```powershell
python scripts\send_campaign_preview.py --campaign-number 1
python scripts\send_campaign_preview.py --campaign-number 2 --dry-run
python scripts\send_campaign_preview.py --all
```

Por padrao, o preview vai para `5531994963959` e usa `Hugo` em `{{decisor}}`.
Use `--phone` e `--decisor` para sobrescrever. O card automatico de link fica
desativado por padrao; use `--link-preview` somente para testar esse card.
Quando a campanha tiver `image_path`, o preview envia a imagem como midia com a
mensagem no caption, igual ao disparo real.

Subir API local/FastAPI:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker / EasyPanel

O projeto tem dois containers separados:

```text
Dockerfile          API FastAPI
Dockerfile.worker   Worker/cron de disparo da fila Redis
```

Tambem e necessario um servico Redis interno no EasyPanel.

API:

```bash
docker build -t whatsapp-mkt-api -f Dockerfile .
docker run --env-file .env -p 8000:8000 whatsapp-mkt-api
```

Worker/cron:

```bash
docker build -t whatsapp-mkt-worker -f Dockerfile.worker .
docker run --env-file .env whatsapp-mkt-worker
```

No EasyPanel:

```text
Servico API
- Dockerfile: Dockerfile
- Porta interna: 8000
- Health check: /health
- Dominio: https://SEU_DOMINIO
- Variavel REDIS_URL apontando para o servico Redis

Servico Worker
- Dockerfile: Dockerfile.worker
- Sem dominio publico
- Mesmo conjunto de variaveis de ambiente da API
- Variavel REDIS_URL apontando para o servico Redis

Servico Redis
- Sem dominio publico
- Persistencia/volume ativado, se disponivel
```

Variaveis Redis:

```env
REDIS_URL=redis://redis:6379/0
REDIS_QUEUE_PREFIX=whatsapp_mkt
REDIS_VISIBILITY_TIMEOUT_SECONDS=300
REDIS_RETRY_DELAY_SECONDS=300
REDIS_MAX_ATTEMPTS=3
```

Variaveis especificas do worker:

```env
WORKER_INTERVAL_SECONDS=60
WORKER_BATCH_SIZE=1
```

Com `WORKER_BATCH_SIZE=1`, o worker processa no maximo uma mensagem por ciclo. O intervalo real entre mensagens tambem respeita `scheduled_at` da fila Redis e o rate limit interno quando o lote tiver mais de uma mensagem.

Chaves Redis usadas pela fila:

```text
whatsapp_mkt:scheduled    mensagens agendadas/prontas para envio
whatsapp_mkt:processing   mensagens em processamento com visibility timeout
whatsapp_mkt:failed       mensagens que excederam tentativas
whatsapp_mkt:message:*    payload de cada mensagem ativa
```

## Webhooks

Webhook para configurar na Evolution API para receber eventos:

```text
POST https://SEU_DOMINIO/webhooks/evolution
```

Endpoint protegido para disparo manual/controlado:

```text
POST https://SEU_DOMINIO/webhooks/dispatch
```

Configure antes:

```env
APP_PUBLIC_URL=https://SEU_DOMINIO
DISPATCH_WEBHOOK_TOKEN=um-token-longo-e-secreto
# Tambem aceito pelo app, se ja estiver usando esse nome:
EVOLUTION_TOKEN=um-token-longo-e-secreto
```

Headers aceitos:

```text
X-Dispatch-Token: um-token-longo-e-secreto
Authorization: Bearer um-token-longo-e-secreto
```

Enviar mensagem direta de teste:

```powershell
curl.exe -X POST "https://SEU_DOMINIO/webhooks/dispatch" `
  -H "Content-Type: application/json" `
  -H "X-Dispatch-Token: SEU_TOKEN" `
  -d "{\"phone\":\"5511999999999\",\"message\":\"Ola! Veja esse post: https://instagram.com/p/Dbq1A8roEjQ/\",\"link_preview\":false}"
```

Disparar uma campanha da fila de forma controlada:

```powershell
curl.exe -X POST "https://SEU_DOMINIO/webhooks/dispatch" `
  -H "Content-Type: application/json" `
  -H "X-Dispatch-Token: SEU_TOKEN" `
  -d "{\"campaign_id\":1,\"batch_size\":1}"
```

Rodar disparo de uma campanha:

```powershell
python scripts\run_campaign.py --campaign-id 1
```

## Proximo Passo

Antes de disparar para os leads reais:

1. Testar a conexao da Evolution API e confirmar que a instancia esta conectada.
2. Enviar uma mensagem de teste para um numero nosso.
3. Confirmar se o link curto do Instagram chega sem card automatico no WhatsApp.
4. Rodar um teste controlado com `--batch-size 1` na Campanha 1.
5. Se tudo estiver certo, deixar o agendamento rodar campanha por campanha.

Comando sugerido para a proxima retomada:

```powershell
python scripts\test_send.py --phone SEU_NUMERO --message "Ola! Veja esse post: https://instagram.com/p/Dbq1A8roEjQ/"
```
