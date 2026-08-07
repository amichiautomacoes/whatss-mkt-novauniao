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
- Saudacao personalizada com `{{decisor}}`.
- Preview de link ativado na Evolution API com `linkPreview: true`.
- Fila ativa de disparo em Redis.
- Supabase usado para leads, campanhas, opt-outs e historico/eventos.
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

## Agendamento Inicial

Rate limit conservador:

```text
1 mensagem por minuto
manha: 10:00
tarde: 14:00
timezone: America/Sao_Paulo
```

Campanhas ja agendadas:

```text
Campanha 1 | lote1 | 10/08/2026 | 70 mensagens
Campanha 2 | lote2 | 11/08/2026 | 70 mensagens
Campanha 3 | lote3 | 12/08/2026 | 69 mensagens
Campanha 4 | lote4 | 13/08/2026 | 69 mensagens
Campanha 5 | lote5 | 14/08/2026 | 69 mensagens
```

Distribuicao:

```text
lotes de 70: 35 manha, 35 tarde
lotes de 69: 35 manha, 34 tarde
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

Recriar/agendar as campanhas iniciais:

```powershell
python scripts\schedule_initial_campaigns.py
```

Enviar mensagem de teste:

```powershell
python scripts\test_send.py --phone 5511999999999 --message "Ola! Veja esse post: https://www.instagram.com/p/Dbq1A8roEjQ/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA=="
```

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
  -d "{\"phone\":\"5511999999999\",\"message\":\"Ola! Veja esse post: https://www.instagram.com/p/Dbq1A8roEjQ/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA==\",\"link_preview\":true}"
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
3. Confirmar se o preview do Instagram aparece corretamente no WhatsApp.
4. Rodar um teste controlado com `--batch-size 1` na Campanha 1.
5. Se tudo estiver certo, deixar o agendamento rodar campanha por campanha.

Comando sugerido para a proxima retomada:

```powershell
python scripts\test_send.py --phone SEU_NUMERO --message "Ola! Veja esse post: https://www.instagram.com/p/Dbq1A8roEjQ/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA=="
```
