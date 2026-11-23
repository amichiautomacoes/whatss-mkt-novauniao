# WhatsApp Marketing Nova União

Automação em Python para enviar campanhas pela Evolution API aos contatos de
`mkt_novauniao.whatsapp_marketing`, com agenda baseada nas aberturas de e-mail
e controle persistente em `mkt_novauniao.whatsapp_historico`.

## Estado atual

As tabelas operacionais foram criadas em 17/11/2026. O histórico também recebeu
a coluna `email_opened_at`, para registrar a abertura que originou o envio.

O worker usa o Supabase como fonte do agendamento. O trigger existente continua
alimentando a origem; o projeto não modifica esse trigger nem altera os leads.
O Google Sheets não faz parte da rotina automática.

A implantação dos containers e o teste real com um número interno são etapas
separadas. As alterações e validações do agendamento não iniciam o worker.

Os arquivos para implantação estão preparados para dois serviços App no
EasyPanel: API na porta interna **8080** e worker sem portas publicadas.
Siga o [guia de implantação](docs/how-to/implantar-easypanel.md) e use
[.env.easypanel.example](.env.easypanel.example) como modelo de ambiente.

## Regra de envio

A data do WhatsApp é **o dia calendário seguinte à primeira abertura do e-mail,
às 14h no fuso America/Sao_Paulo**, incluindo fins de semana.

| Primeira abertura em São Paulo | Início previsto |
|---|---|
| 17/11/2026 às 09h | 18/11/2026 às 14h |
| 17/11/2026 às 23h50 | 18/11/2026 às 14h |
| 18/11/2026 às 00h10 | 19/11/2026 às 14h |

A regra usa `primeira_abertura`, convertida para o fuso da campanha. Novas
aberturas do mesmo e-mail não adiam um agendamento reservado. A data do envio
do e-mail e a data de criação da linha na origem não entram nesse cálculo.

`WHATSAPP_OPENED_FROM=2026-11-17` é o corte inicial, contado a partir de 00h
em São Paulo. Ele é fixo e configurável, para impedir que a reposição de dados
antigos pelo trigger gere uma abordagem retroativa. Alterar esse corte não
cancela reservas já existentes.

## Fluxo automático

1. O trigger atualiza `whatsapp_marketing` com as aberturas elegíveis.
2. A cada ciclo, o worker consulta primeiras aberturas desde o corte configurado.
3. Normaliza os telefones, escolhe a primeira abertura elegível de cada telefone
   e exclui contatos já reservados naquela campanha de WhatsApp.
4. Reserva o envio no histórico como `pending`, guardando a abertura e a data prevista.
5. No minuto de início das 14h, abre a janela diária de processamento.
6. Enfileira e envia as pendências vencidas da campanha automática pelo Redis.
7. Atualiza o histórico com tentativa, sucesso, erro e resposta da Evolution.

A seleção considera todos os lotes, inclusive contatos sem `lote_key`.
A campanha operacional usa o lote interno `automatico`. O campo `campanha` da
origem descreve o e-mail; `WHATSAPP_CAMPAIGN_NAME` escolhe o template de WhatsApp.

A restrição **nome da campanha de WhatsApp + telefone normalizado** impede
reservas repetidas, inclusive entre lotes e em ciclos ou processos concorrentes.
O limite de descoberta é aplicado depois da exclusão pelo histórico e da
deduplicação, para não ficar preso nos primeiros contatos já processados.

## Janela diária e retomada

14h é o início da fila. Com um envio por ciclo de 60 segundos, os contatos
seguintes são processados aproximadamente às 14h01, 14h02 e assim por diante.

A janela abre quando um ciclo ocorre no minuto configurado, das 14h00min00s
até antes de 14h01min00s. O worker ajusta a espera para acordar no início.
Depois de aberta, ela continua até o fim do dia local, respeitando os intervalos.

Se o worker iniciar ou reiniciar após esse minuto, aguarda as 14h do dia
seguinte. Uma falha operacional não tratada durante a janela fecha o processamento
daquele dia; pendências ficam para a próxima janela das 14h. O agendamento
original fica no histórico, permitindo identificar atrasos.

O processamento considera reservas criadas antes do fim do minuto de abertura.
Contatos que só se tornarem elegíveis depois desse limite aguardam a próxima
janela, mesmo quando a data originalmente calculada já tiver passado.

Os resultados `uncertain` continuam exigindo conferência manual, pois pode ter
ocorrido um envio sem que a resposta fosse recebida. Eles não são reenviados
automaticamente na janela seguinte.

Use uma instância do worker para esta rotina. A abertura da janela fica na
memória do processo, de modo que um reinício fora das 14h aguarde o próximo dia.
`WHATSAPP_SCHEDULE_DRY_RUN=true` bloqueia reservas e disparos, inclusive se já
existirem pendências; `WHATSAPP_SCHEDULE_ENABLED=false` desativa a rotina.

## Origem e histórico

Campos usados em `whatsapp_marketing`:

| Campo | Uso |
|---|---|
| `id` | Copiado como `source_id` no histórico |
| `lead_key` | Identificação UUID do lead |
| `telefone_contato` | Telefone do destinatário |
| `nome_decisor`, `empresa`, `email`, `lote_key` | Personalização |
| `primeira_abertura` | Cálculo do dia seguinte às 14h |

Templates existentes com `{{decisor}}` e `{{lote}}` continuam funcionando,
assim como `{{nome_decisor}}` e `{{lote_key}}`.

Tabelas operacionais:

- `whatsapp_campaigns`: configuração das campanhas.
- `whatsapp_historico`: reserva, horário previsto, tentativas e resultado.
- `whatsapp_opt_outs`: telefones excluídos do envio.

O histórico inclui `email_opened_at`, `scheduled_at`, `last_attempt_at`,
`sent_at`, `status`, `attempts`, `message`, `image_path`,
`provider_message_id`, `provider_response` e `last_error`.
Datas usam `timestamptz`. `source_id` e `lead_key` são referências copiadas,
sem chave estrangeira para a origem, preservando o histórico após uma limpeza.

| Status | Significado |
|---|---|
| `pending` | Reservado ou aguardando nova tentativa conhecida |
| `processing` | Tentativa registrada antes da chamada à Evolution |
| `sent` | Chamada à Evolution concluída com sucesso |
| `failed` | Limite de tentativas conhecido atingido |
| `cancelled` | Contato excluído por opt-out |
| `uncertain` | Resultado exige conferência antes de reenviar |

Timeout, HTTP 5xx e tentativa interrompida geram resultado incerto.
Rejeições HTTP 4xx e falhas locais anteriores à chamada respeitam o limite
de tentativas. Quando a resposta foi preservada no Redis, o histórico pode
ser reconciliado sem repetir o envio.

Registros já reservados não são selecionados de novo pela descoberta, inclusive
falhas e cancelamentos. Outra campanha representa uma nova abordagem.

`sent` não confirma entrega ou leitura no celular. O webhook da Evolution ainda
só recebe os eventos; persistir entrega, leitura, resposta e opt-out pelo webhook
continua pendente. Opt-outs cadastrados na tabela já são respeitados.

## Configuração e execução

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure as credenciais de banco, Evolution e Redis no ambiente dos containers.
Redis e Evolution não precisam rodar nesta máquina.

Variáveis principais:

```env
SUPABASE_SCHEMA=mkt_novauniao
WHATSAPP_CAMPAIGN_NAME=Natal 2026
WHATSAPP_OPENED_FROM=2026-11-17
WHATSAPP_SEND_TIME=14:00
CAMPAIGN_TIMEZONE=America/Sao_Paulo
WHATSAPP_SCHEDULE_ENABLED=true
WHATSAPP_SCHEDULE_DRY_RUN=false
WHATSAPP_SCHEDULE_LIMIT=500
WORKER_INTERVAL_SECONDS=60
WORKER_BATCH_SIZE=1
DEFAULT_SEND_DELAY_SECONDS=60
```

`WHATSAPP_SCHEDULE_LIMIT` limita novos contatos por descoberta, não por dia.
O ciclo aceita intervalo de 1 a 60 segundos para acompanhar o minuto de início.
A campanha desta etapa é `Natal 2026`, com texto personalizado e sem imagem.
Selecione-a explicitamente em `WHATSAPP_CAMPAIGN_NAME`. O código não escolhe outro
template se essa variável estiver vazia. Confira a prévia antes da operação real.

Preparar tabelas ou acrescentar colunas novas em outro ambiente:

```powershell
python scripts\create_operational_tables.py --dry-run
python scripts\create_operational_tables.py
```

O script é idempotente e não limpa a origem, não altera triggers e não importa
eventos de versões anteriores.

Simular a seleção e conferir a quantidade de candidatos, sem criar reservas ou
enviar mensagens:

```powershell
python scripts\run_opened_campaign.py --dry-run
```

Executar `run_opened_campaign.py` sem `--dry-run` apenas cria as reservas,
sem acessar Redis ou Evolution. Para a automação contínua:

```powershell
python scripts\cron_worker.py
```

O worker pode fazer envios reais na janela diária. A API pode ser iniciada com:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Templates, fila e infraestrutura

A campanha `Natal 2026` e os cinco templates antigos estão em
`campanhas/campanhas_extraidas.json`. Os links curtos da campanha foram conferidos;
o link de orçamento preserva o texto pré-preenchido do WhatsApp. Os destinos
originais também ficam no JSON para consulta. Campanhas com imagem são
enviadas como mídia com o texto no caption. O preview de links fica desativado.

```powershell
python scripts\send_campaign_preview.py --campaign-name "Natal 2026" --dry-run
```

A fila usa `REDIS_QUEUE_PREFIX:v2`, por exemplo `whatsapp_mkt:v2:scheduled`,
`whatsapp_mkt:v2:processing`, `whatsapp_mkt:v2:failed` e
`whatsapp_mkt:v2:message:history:123`. Entradas antigas sem ID do histórico
ficam isoladas no namespace anterior. Enfileirar novamente preserva uma
mensagem que já está em processamento.

- `Dockerfile`: API FastAPI, porta 8080, health check `GET /health`.
- `Dockerfile.worker`: worker, sem domínio público e sem porta publicada.
- Ambos executam com usuário sem privilégios e incluem os templates da campanha.
- Redis e Evolution acessíveis pelos endereços do ambiente dos containers.
- API e worker com credenciais compatíveis e tabelas preparadas.

Endpoints: `POST /webhooks/evolution` e `POST /webhooks/dispatch`.
O dispatch exige `DISPATCH_WEBHOOK_TOKEN` (ou `EVOLUTION_TOKEN`) em
`X-Dispatch-Token` ou `Authorization: Bearer ...`.

Mensagens diretas, previews e `run_campaign.py` são operações manuais e não
seguem o controle de abertura da janela do worker. Os utilitários Google Sheets
foram mantidos para uso manual legado; o worker não os importa nem consulta a
planilha. Credenciais Google não são necessárias para a automação atual.

## Preparação para o GitHub

O remoto `origin` aponta para
`amichiautomacoes/whatss-mkt-novauniao`, branch `main`. A preparação dos arquivos
não faz commit, push ou implantação.

`.env`, chaves privadas, credenciais Google, ambientes virtuais e arquivos
locais estão excluídos do Git e do contexto Docker. Somente os modelos de
ambiente sem credenciais devem ser versionados. Cadastre os valores reais
diretamente no EasyPanel.

O workflow [.github/workflows/ci.yml](.github/workflows/ci.yml) executa os testes
e constrói as duas imagens em pushes para `main`, pull requests ou acionamento
manual. Também confere imports, fuso horário, usuário do container e a resposta
de `/health`, sem acessar Supabase, Redis ou Evolution. Ele não publica imagens
nem implanta serviços.

As dependências diretas estão fixadas nas versões do ambiente validado.
`tzdata` garante os dados do fuso `America/Sao_Paulo` na imagem Python.

## Testes

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes bloqueiam conexões reais ao banco, Redis e Evolution. A fila usa
Redis simulado com execução de Lua. São cobertos cálculo por calendário local,
corte de elegibilidade, primeira abertura, simulação, opt-out, duplicidade,
retomada na próxima janela e preservação do resultado após falhas.
