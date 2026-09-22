# Antevê

Radar nacional de recuperações judiciais para escritórios de advocacia. Detecta novos pedidos após o protocolo, organiza evidências oficiais, separa fato processual de inferência comercial e gera oportunidades auditáveis. Implementa a Especificação do Sistema de Monitoramento de Recuperações Judiciais, versão 1.0 de 22/09/2026.

## Princípio de funcionamento

O sistema opera com duas camadas independentes. A camada de detecção confirmada só afirma que existe recuperação judicial com fonte oficial (metadado do DataJud, publicação oficial ou documento do processo). A camada preventiva calcula um score explicável de sinais públicos e licenciados e é sempre rotulada como "Recuperação judicial não confirmada". A IA nunca é fonte primária: só é acionada quando já há texto oficial coletado, e sua resposta passa pelas regras da seção 7.1 antes de ser aceita.

## Instalação

Requisitos: Python 3.11 ou superior. O servidor deve estar no Brasil, porque a API do Diário de Justiça Eletrônico Nacional (DJEN) recusa acessos de fora do país. Sem `DATABASE_URL`, o banco é um arquivo SQLite local. Com `DATABASE_URL`, o sistema usa PostgreSQL, que é o motor recomendado para produção.

```bash
pip install -r requirements.txt
python -m anteve.cli tpu                                            # sincroniza a TPU com o SGT/CNJ
python -m anteve.cli reconciliar --dias 365                         # carga inicial de 12 meses
python -m anteve.cli servir --porta 8000                            # painel, API e agendador
```

Abra `http://servidor:8000` e entre com usuário e senha. O administrador inicial é criado automaticamente (veja Login e senha). A documentação interativa da API fica em `/docs`.

Com Docker:

```bash
docker build -t anteve .
docker run -d -p 8000:8000 -v anteve_dados:/app/data --env-file .env anteve
```

## Publicação no GitHub e no Vercel

O repositório já vem pronto para as duas plataformas:

* `api/index.py` é a função Python do Vercel.
* `vercel.json` fixa a região em São Paulo (`gru1`), limita cada execução a 60 segundos e agenda a reconciliação diária.
* `.github/workflows/testes.yml` roda os testes em SQLite e em PostgreSQL a cada push.
* `.github/workflows/coleta.yml` dispara a coleta incremental a cada 10 minutos.

A região em São Paulo também resolve o bloqueio geográfico do DJEN.

### 1. Banco PostgreSQL

O Vercel não guarda arquivos entre execuções, por isso o SQLite não serve em produção. Crie um PostgreSQL na região de São Paulo; o Supabase em `sa-east-1` é a opção mais direta. Guarde duas URLs de conexão:

* **URL do pooler em modo transação (porta 6543):** para o Vercel. O sistema já desativa *prepared statements*, como esse modo exige.
* **URL direta ou em modo sessão (porta 5432):** para a carga inicial pela linha de comando.

### 2. GitHub

```bash
git init
git add .
git commit -m "Antevê 1.0"
git branch -M main
git remote add origin https://github.com/<organizacao>/anteve.git
git push -u origin main
```

Crie o repositório como **privado**. A aba Actions mostrará o workflow Testes rodando.

### 3. Vercel

1. Em Add New > Project, importe o repositório. O Vercel detecta Python pelo `requirements.txt`; não altere comandos de build.
2. Em Settings > Environment Variables, configure:
   * `DATABASE_URL`: URL do pooler.
   * `CRON_SECRET`: um valor longo e aleatório, por exemplo gerado com `openssl rand -hex 32`.
   * `ANTEVE_ADMIN_SENHA`: senha do administrador `joao.zocarato`. Se definida, substitui a senha inicial a cada deploy.
   * `ANTEVE_IPS_PERMITIDOS`: IPs autorizados, separados por vírgula. O padrão já traz os IPs da SBK (186.193.236.194 e 179.191.112.34).
   * Opcionais: `ANTHROPIC_API_KEY` e as variáveis de SMTP.
3. Faça o deploy e confira `https://<projeto>.vercel.app/api/saude`. A resposta deve mostrar `"banco": "postgresql"` e `"persistente": true`.

### 4. Carga inicial

Estes comandos rodam uma única vez, da sua máquina, apontando para o mesmo banco:

```bash
pip install -r requirements.txt
export DATABASE_URL="<URL direta, porta 5432>"
python -m anteve.cli tpu
python -m anteve.cli reconciliar --dias 365
```

Sem essa carga, o botão **Executar coleta agora** (tela Fontes e saúde) já traz os últimos 30 dias: ele percorre os 27 TJs em lotes de 6, cada um dentro do limite de uma função do Vercel. A reconciliação de 12 meses leva alguns minutos. Ela é feita pela linha de comando porque não cabe no limite de 60 segundos de uma função.

Para ativar o acesso ao DJEN já na carga inicial, execute a partir de uma máquina no Brasil. Depois disso, o próprio Vercel em `gru1` completa as publicações a cada ciclo.

### 5. Agendamento

No repositório do GitHub, em Settings > Secrets and variables > Actions, crie:

* o *secret* `CRON_SECRET`, com o mesmo valor configurado no Vercel;
* a *variable* `APP_URL`, com o endereço do projeto.

A partir daí o workflow Coleta agendada chama `/api/cron/coleta` a cada 10 minutos. Cada chamada processa 6 tribunais em paralelo e continua do ponto em que a anterior parou, então os 27 TJs são percorridos em cerca de 50 minutos. Se um tribunal não terminar dentro do prazo, o cursor fica no último registro processado e a coleta retoma dali, sem perda. A tela Fontes e saúde mostra esse caso como PARCIAL.

A reconciliação diária de 30 dias é disparada pelo Cron do próprio Vercel às 9h UTC (6h em Brasília).

No plano Pro do Vercel, também é possível trocar o workflow do GitHub por um Cron do Vercel com a expressão `*/10 * * * *`, apontando para `/api/cron/coleta`.

### Observações sobre o Vercel

* **Plano:** o plano Hobby do Vercel é restrito a uso não comercial pelos termos da plataforma. Para prospecção de escritório, use o plano Pro.
* **Limites do plano Hobby:** ele aceita apenas Cron diário, por isso a coleta frequente vem do GitHub Actions.
* **Prazo por execução:** `ANTEVE_ORCAMENTO_S` (padrão 45) controla quanto tempo cada chamada trabalha antes de parar com segurança. `ANTEVE_PARALELO` (padrão 6) controla quantos tribunais entram em cada lote.
* **Agendador interno:** fica desligado automaticamente no Vercel. Em servidor próprio ou Docker, ele continua funcionando como antes.

## Restrição de acesso

O painel e a API só respondem aos IPs de `ANTEVE_IPS_PERMITIDOS`. Qualquer outro endereço recebe 403 antes mesmo da tela de login. As rotas `/api/cron/*` ficam fora da restrição porque são chamadas pelo Vercel Cron e pelo GitHub Actions, e continuam protegidas pelo `CRON_SECRET`. No Vercel, o IP é lido do `X-Forwarded-For`, que a plataforma sobrescreve. Em servidor próprio atrás de proxy, defina `ANTEVE_CONFIAR_PROXY=1`.

## Perfis de acesso

| Perfil | Pode |
| --- | --- |
| admin | tudo, inclusive coleta manual, sincronização da TPU, amostra de controle e auditoria |
| analista | ler, revisar, camada preventiva e exportar |
| comercial | ler e operar o funil de oportunidades |
| leitor | apenas consultar |

Os usuários são administrados na tela **Usuários**, visível só para o perfil admin. Lá é possível incluir um usuário (com senha digitada ou gerada automaticamente), gerar uma nova senha e excluir um usuário. A senha gerada aparece uma única vez. Trocar a senha ou excluir o usuário encerra na hora as sessões abertas. Não é possível excluir o próprio usuário nem o último administrador. Pela linha de comando: `python -m anteve.cli iniciar --nome "Nome" --login nome.sobrenome --senha "..." --papel analista`.

## Login e senha

O acesso é por usuário e senha. Na primeira execução o sistema cria o administrador definido em `ANTEVE_ADMIN_LOGIN` (padrão `joao.zocarato`) com a senha inicial `1234`. Troque essa senha definindo `ANTEVE_ADMIN_SENHA` no Vercel e fazendo um novo deploy. Senhas são guardadas apenas como hash PBKDF2. Cada login abre uma sessão assinada, que vale em qualquer instância do Vercel e expira em `ANTEVE_SESSAO_HORAS` (padrão 12). A chave de assinatura vem de `ANTEVE_SEGREDO`; na falta dela, do `CRON_SECRET` ou da URL do banco. Se `ANTEVE_ADMIN_SENHA` estiver definida, ela prevalece sobre uma senha do administrador gerada pela tela a cada novo deploy. Tentativas de login, com acerto ou falha, ficam na auditoria com o IP de origem.

## Rotina automática

O agendador roda a cada 45 minutos (ajustável em `ANTEVE_INTERVALO_MIN`) e executa, nesta ordem:

1. **Coleta incremental por tribunal:** usa o DataJud com cursor próprio de cada tribunal e janela sobreposta de 72 horas.
2. **Consulta de segurança:** procura atos recuperacionais (RJ concedida, decreto de falência) em processos fora da classe RJ, para capturar erros de autuação.
3. **Busca de publicações no DJEN:** atende os processos ativos que ainda não têm documento oficial.
4. **Recálculo dos scores preventivos:** os pesos expiram conforme a validade de cada sinal.
5. **Reconciliações:** a diária cobre os últimos 30 dias e a mensal os últimos 12 meses, ambas por data de ajuizamento.

Se uma fonte falha, o cursor não avança e a tela Fontes e saúde mostra o motivo. A ausência de resposta nunca é tratada como ausência de processo.

## Particularidades das fontes validadas em 22/09/2026

* **DataJud, filtro de data:** o campo `dataAjuizamento` é gravado no formato compacto `yyyyMMddHHmmss`, e o filtro por faixa só funciona corretamente nesse formato. O exemplo conceitual da seção 8, que usa data ISO, retorna resultados errados. O conector já usa o formato certo e emprega `dataHoraUltimaAtualizacao` (data ISO) como cursor.
* **DataJud, partes:** a API pública não informa partes nem CNPJ. Por isso, todo pedido detectado só pelo DataJud entra com confiança máxima de 0,70 e contato bloqueado. Na tela de revisão, o analista vincula o CNPJ com uma evidência, e o cadastro da empresa é consultado automaticamente. As publicações do DJEN fazem esse vínculo sozinhas quando o CNPJ aparece junto a "recuperanda" ou "requerente".
* **DataJud, latência:** no dia da validação, o pedido mais recente disponível era de 08/09 e o atraso médio entre ajuizamento e disponibilidade ficou em torno de 24 dias. A meta de latência da especificação (P50 até 2 h) é medida a partir da disponibilidade na fonte. A antecipação em relação ao ajuizamento depende do DJEN e de conectores de portais de tribunal.
* **TPU:** os 32 códigos usados pelas regras foram conferidos como vigentes no SGT/CNJ. O movimento 12041 é "Concedida a recuperação judicial".

## Resultado da primeira carga real (12 meses, 27 TJs)

| Item | Quantidade |
| --- | --- |
| Pedidos de recuperação judicial com classe oficial | 1.483 |
| Confirmados ativos | 812 |
| Provisórios (divergência) | 539 |
| Encerrados (indeferidos, cancelados, desistências) | 132 |
| Pedidos de falência (camada preventiva) | 1.479 |
| Recuperações extrajudiciais (camada separada) | 67 |

As divergências mais frequentes ficaram na fila de revisão, e nenhum desses casos foi apresentado como nova RJ:

| Divergência | Casos |
| --- | --- |
| Distribuição por dependência (possível incidente ou litisconsórcio de grupo) | 328 |
| Incidente de classificação de créditos autuado como RJ | 140 |
| Classe RJ com assunto recuperação extrajudicial | 78 |

## Estrutura

| Módulo | Responsabilidade (seção 8.1) |
| --- | --- |
| `orchestrator.py` | Orquestrador: agenda, cursores, retentativas, reconciliações, saúde |
| `connectors/datajud.py` | Conector DataJud com paginação em streaming |
| `connectors/djen.py` | Coletor de diário (DJEN) |
| `connectors/cnpj.py` | Cadastro CNPJ por dados abertos da Receita, sem guardar sócios |
| `normalize.py` | CNJ com dígito verificador, CNPJ inclusive alfanumérico, datas, nomes |
| `tpu.py` | Dicionário TPU versionado e sincronização com o SGT |
| `rules.py` | Taxonomia, exclusões, rotas A a D, estágio, idade, prioridade, confiança |
| `documentos.py` | Leitura determinística de publicações: ato, requerente, administrador judicial |
| `classifier.py` | Prompt da seção 7 e regras posteriores ao modelo |
| `scoring.py` | Score preventivo com expiração, sinais negativos e salvaguardas |
| `pipeline.py` | Fluxo funcional da seção 5, deduplicação, identidade, oportunidades |
| `notifier.py` | Gates de qualidade, preferências e canais (painel, e-mail, webhook, Slack, Teams) |
| `api.py` | API, perfis, auditoria, métricas, exportação |
| `static/index.html` | Painel |
| `api/index.py` | Entrada da função no Vercel |
| `vercel.json` | Região São Paulo, limite de execução, rotas e Cron |
| `.github/workflows/` | Testes a cada push e coleta agendada |

## Configuração

Todas as variáveis estão em `.env.example`. As principais são estas:

* **Coleta:** `ANTEVE_TRIBUNAIS` define os tribunais monitorados.
* **Definição de "novo":** `ANTEVE_NOVO_DIAS` e `ANTEVE_RECENTE_DIAS`.
* **IA:** `ANTHROPIC_API_KEY` ativa o classificador.
* **E-mail:** `SMTP_HOST` e as variáveis relacionadas.
* **Camada preventiva:** `ANTEVE_PREVENTIVO_REVISAO=1` mantém a exigência de revisão humana antes de qualquer alerta preventivo, que é o comportamento recomendado nas fases iniciais.

## Testes

```bash
python -m pytest -q tests
```

São 36 testes. Eles cobrem todos os cenários obrigatórios da seção 11.2, as regras de score da seção 4, as regras posteriores ao modelo da seção 7.1, os gates de notificação e a retomada após execução parcial. Para rodar os mesmos testes em PostgreSQL, defina `TEST_DATABASE_URL`. O GitHub Actions executa as duas versões a cada push.

## Métricas

A tela Métricas mostra os indicadores da especificação:

* **Cobertura:** exige uma amostra oficial de controle, carregada em `POST /api/controle`.
* **Precisão:** passa a ser calculada depois das primeiras decisões da fila de revisão.
* **Latência:** medida a partir da disponibilidade na fonte, com o atraso judicial exibido à parte.
* **Deduplicação e rastreabilidade:** calculadas continuamente.

## Governança

* **Sigilo:** processos sigilosos são excluídos sem persistência de metadados.
* **Preventivo:** o score nunca é exportado nem publicado em lista.
* **Auditoria:** consultas, decisões, exportações, vínculos de identidade e mudanças de TPU vão para a trilha de auditoria.
* **Opt out:** bloqueia contato e remove a empresa da exportação.
* **Correções:** podem ser abertas por qualquer perfil e seguem para a fila de revisão.
* **Linguagem:** os alertas seguem as expressões permitidas da seção 10.2 e terminam com "Classificação sujeita a validação jurídica".

Por norma interna de escrita, os assuntos dos alertas usam barra vertical no lugar do travessão.

## Antes de operar comercialmente

Como exige a especificação, o produto deve ser revisado pelo jurídico e pelo encarregado de dados antes de operar comercialmente. Também faltam as decisões da seção 13:

* cobertura inicial;
* latência comercial;
* critério de oportunidade;
* fontes contratadas;
* política de contato;
* integrações;
* prazos de retenção.


