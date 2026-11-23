# Implantar a automação no EasyPanel

Status: Draft — arquivos preparados; primeira implantação pendente.

Use dois serviços App ligados ao mesmo repositório: um para receber requisições
HTTP e outro para executar a automação. A API usa a porta interna **8080**.
O worker não publica portas e precisa de **uma única réplica**.

Tenha acesso ao EasyPanel, ao repositório GitHub e aos endereços e credenciais
remotos do PostgreSQL/Supabase, Redis e Evolution. Este projeto não cria esses
três serviços. As tabelas operacionais precisam existir no banco de destino.

## Publique os arquivos e confira a validação

1. Confira as alterações e os arquivos que entrarão no Git:

   ```powershell
   git status --short
   git diff --check
   ```

2. Faça o commit e publique quando os arquivos estiverem revisados:

   ```powershell
   git add .
   git commit -m "Prepara automacao Supabase e containers para EasyPanel"
   git push origin main
   ```

3. No GitHub, aguarde o workflow **Validate project**. Ele executa os testes,
   constrói as imagens e faz verificações sem acesso aos serviços de produção.
   O workflow não faz deploy.

Os modelos [.env.example](../../.env.example) e
[.env.easypanel.example](../../.env.easypanel.example) não contêm credenciais.
Não acrescente valores reais a esses arquivos. O `.env` local e as chaves
privadas estão excluídos em [.gitignore](../../.gitignore) e
[.dockerignore](../../.dockerignore).

## Configure o serviço da API na porta 8080

1. No projeto do EasyPanel, crie um serviço **App** chamado `whatsapp-api`.
2. Em **Source**, selecione **GitHub** e informe
   `amichiautomacoes/whatss-mkt-novauniao`, branch `main` e Build Path `/`.
   Se o repositório for privado, configure o acesso do EasyPanel ao GitHub.
3. Em **Build**, escolha **Dockerfile** e informe `Dockerfile` como caminho.
   Use a fonte GitHub para disponibilizar os arquivos do repositório no build.
4. Em **Environment**, cole o conteúdo de
   [.env.easypanel.example](../../.env.easypanel.example) e preencha:

   - `SUPABASE_DATABASE_URL`: conexão PostgreSQL do banco de destino.
   - `REDIS_URL`: conexão com o Redis remoto, incluindo autenticação, se exigida.
   - `EVOLUTION_API_URL`: endereço base da Evolution acessível pelo container.
   - `EVOLUTION_API_KEY`: chave da Evolution.
   - `EVOLUTION_INSTANCE`: instância cadastrada e conectada ao WhatsApp.
   - `DISPATCH_WEBHOOK_TOKEN`: token de autenticação do endpoint de dispatch.
   - `APP_PUBLIC_URL`: URL HTTPS atribuída à API no EasyPanel.

5. Mantenha `PORT=8080`. Em **Domains**, configure HTTP e a porta de destino
   **8080**. O proxy do EasyPanel oferece o domínio HTTPS; não é necessário
   publicar uma porta do host na seção **Ports**.
6. Deixe o comando de inicialização vazio, para usar o comando da imagem, e
   selecione **Deploy**.

O [Dockerfile](../../Dockerfile) inicia o Uvicorn em `0.0.0.0:8080`, com usuário
sem privilégios e verificação periódica de `/health`. O endereço
`https://SEU_DOMINIO/health` deve responder `{"status":"ok"}`. Essa resposta
confirma a API em execução; não verifica as conexões com os serviços remotos.

Use nomes DNS ou URLs acessíveis a partir dos containers. `localhost` aponta
para o próprio container. Se os serviços estiverem em redes Docker diferentes,
configure a conectividade no servidor ou utilize os endereços remotos que já
estejam disponíveis. Preserve as opções de TLS exigidas por cada conexão.

O endpoint disponível para eventos da Evolution é
`https://SEU_DOMINIO/webhooks/evolution`. O recebimento ainda não atualiza os
estados de entrega, leitura, resposta ou opt-out no banco, conforme descrito no
[README](../../README.md).

## Configure o worker sem domínio nem portas

1. Crie outro serviço **App** chamado `whatsapp-worker`.
2. Selecione a mesma fonte GitHub, branch `main` e Build Path `/`.
3. Em **Build**, selecione **Dockerfile** e informe `Dockerfile.worker`.
4. Copie as variáveis do modelo e preencha as mesmas conexões do ambiente remoto.
   Não é necessário fornecer credenciais Google.
5. Remova qualquer domínio criado automaticamente e deixe **Ports** vazio.
   O worker não atende HTTP; `PORT` e `APP_PUBLIC_URL` não são usados por ele.
6. Configure **uma réplica** e desative o deploy sem interrupção para evitar
   sobreposição de workers durante atualizações. Mantenha o comando padrão.
7. Mantenha `WHATSAPP_SCHEDULE_DRY_RUN=true` na primeira implantação e faça
   **Deploy**.

O [Dockerfile.worker](../../Dockerfile.worker) executa
`python scripts/cron_worker.py`. Os logs aparecem no próprio EasyPanel.
O modo de simulação consulta os candidatos no Supabase, sem criar reservas nem
enviar mensagens pelo worker. Esse modo não bloqueia os utilitários manuais de
envio nem o endpoint de dispatch; eles não fazem parte desta validação.

As imagens incluem o código e os templates. O estado operacional fica no
PostgreSQL e no Redis; API e worker não precisam de volumes locais para essa
rotina.

## Valide as conexões e ative o agendamento

1. Confirme a resposta de `/health` na API e a ausência de falhas de conexão nos
   logs do worker em simulação.
2. No console do worker, confira a seleção sem gravar reservas:

   ```sh
   python scripts/run_opened_campaign.py --dry-run
   ```

3. Confirme no ambiente da Evolution que a instância informada está conectada.
   O teste real com um número interno é uma etapa separada da criação dos
   arquivos de implantação.
4. Para operar, altere no worker `WHATSAPP_SCHEDULE_DRY_RUN=false` e faça
   **Deploy**. Mantenha `WHATSAPP_SCHEDULE_ENABLED=true`.

O modelo usa `Natal 2026`, corte em `2026-11-17`, início às `14:00`, fuso
`America/Sao_Paulo` e um envio por ciclo de 60 segundos. O fuso é definido pela
configuração da campanha, independentemente do relógio local do servidor.

Se a implantação ou um reinício terminar depois do minuto das 14h, o worker
aguarda as 14h do dia seguinte. Reiniciar não abre uma janela de envio atrasada.
Consulte a [regra de retomada](../../README.md#janela-diária-e-retomada).

## Corrija falhas de implantação sem apagar o histórico

Se o build falhar, abra o log de implantação do EasyPanel. Se a imagem iniciar
com erros, confira as variáveis, a conectividade e os logs do serviço afetado.
A API precisa escutar em 8080 e o domínio precisa apontar para essa mesma porta.

Para suspender a rotina, use `WHATSAPP_SCHEDULE_ENABLED=false` no worker e
reimplante, ou pare esse serviço no EasyPanel. Preserve o histórico e o Redis.
Registros `uncertain` precisam de conferência antes de qualquer reenvio.

Para reverter o código, reverta o commit no GitHub e reimplante os serviços.
Uma reversão de código não desfaz alterações no banco nem envios já realizados.

Este procedimento segue a
[documentação oficial de serviços App do EasyPanel](https://easypanel.io/docs/services/app).
