# Antevê: Manual do Usuário

Versão 1.0 | 22/09/2026 | Joao Zocarato

## 1. Introdução

O Antevê mostra os novos pedidos de recuperação judicial dos 27 Tribunais de Justiça, com a fonte oficial de cada informação, e ajuda a transformar esses pedidos em oportunidades comerciais. Este manual explica cada tela, card, campo e botão.

**Três conceitos para entender antes de usar:**

- **Confirmado:** existe fonte oficial dizendo que o processo é uma recuperação judicial e nada diverge. Aparece com um selo escuro preenchido.
- **Provisório:** há indício de RJ, mas algo diverge ou falta confirmar. Aparece com borda tracejada e precisa de revisão humana antes de qualquer oferta.
- **Preventivo:** sinais de que uma empresa pode vir a pedir RJ. Nunca é uma RJ confirmada e aparece sempre com a frase "Recuperação judicial não confirmada" e um selo listrado.

**Perfis de acesso:**

| Perfil | O que pode fazer |
| --- | --- |
| Administrador | Tudo, inclusive coleta manual, TPU e gestão de usuários |
| Analista | Consultar, revisar, vincular CNPJ e partes, usar o preventivo e exportar |
| Comercial | Consultar e operar o funil de oportunidades |
| Leitor | Apenas consultar |

Todas as classificações são sujeitas a validação jurídica.

## 2. Acesso ao sistema

O sistema só abre dentro da rede da SBK e pede usuário e senha fornecidos pelo administrador.

**Para entrar:**

1. Acesse o endereço do sistema a partir da rede SBK.
2. Em **Usuário**, digite seu login (por exemplo, `nome.sobrenome`). Maiúsculas não fazem diferença.
3. Em **Senha**, digite sua senha.
4. Clique em **Entrar**.

**Sessão:** depois de entrar, você continua conectado por 12 horas, mesmo recarregando a página. Passado esse tempo, o sistema volta para a tela de login.

**Para sair:** clique em **Sair**, no canto inferior do menu lateral, abaixo do seu nome e perfil.

**Mensagens que podem aparecer:**

| Mensagem | O que significa | O que fazer |
| --- | --- | --- |
| "acesso restrito à rede SBK" | Você está fora da rede autorizada | Conecte-se à rede da SBK |
| "usuário ou senha inválidos" | Login ou senha incorretos | Confira os dados ou peça uma nova senha ao administrador |
| "sessão ausente ou expirada" | A sessão venceu ou a senha foi trocada | Entre novamente |
| Faixa "Banco não persistente" no topo | O sistema está sem banco definitivo; os dados podem sumir | Avise o administrador |

**Esqueceu a senha?** Peça ao administrador para gerar uma nova na tela Usuários.

## 3. Navegação

O menu lateral, à esquerda, leva a todas as telas. Cada perfil vê apenas as telas que pode usar.

| Item do menu | Para que serve | Quem vê |
| --- | --- | --- |
| Novas recuperações | Lista dos pedidos de RJ | Todos |
| Falência e extrajudicial | Pedidos de falência e recuperações extrajudiciais | Todos |
| Revisão humana | Casos que precisam de decisão; o número ao lado mostra quantos estão pendentes | Admin e analista |
| Preventivo | Score de sinais de risco por empresa | Admin e analista |
| Alertas | Histórico de alertas gerados | Todos |
| Fontes e saúde | Situação das fontes e botões de coleta | Todos (botões só para admin) |
| Métricas | Indicadores de qualidade | Todos |
| Preferências | O que você quer receber de alerta e por onde | Todos |
| Usuários | Incluir, excluir e gerar senhas | Admin |

No rodapé do menu aparecem seu login, seu perfil entre parênteses e o botão **Sair**. No celular, o menu vira uma barra horizontal no topo, com rolagem lateral.

## 4. Novas recuperações judiciais

É a tela principal: a lista dos pedidos de recuperação judicial, ordenada por prioridade e, dentro dela, pelos ajuizados mais recentes. O título, os cards e os filtros ficam fixos; só a tabela rola.

### 4.1 Cards do topo

Os números consideram a base inteira com os filtros aplicados, e não só as linhas exibidas.

| Card | O que conta |
| --- | --- |
| Confirmados ativos | Pedidos com status Confirmado ou Atualizado: validados em fonte oficial |
| Provisórios | Pedidos com divergência ou confirmação insuficiente (status Provisório ou Candidato) |
| Encerrados | Pedidos indeferidos, cancelados, com desistência, baixados ou convolados em falência |
| Contato liberado | Pedidos com CNPJ verificado, confirmados e sem pendência: os únicos que podem ser abordados comercialmente |

### 4.2 Busca e filtros

- **Campo de busca:** aceita número CNJ (completo ou parte), nome da vara, nome de parte ou advogado, razão social ou CNPJ. Acentos e maiúsculas não importam para partes. A busca roda sozinha 0,3 segundo depois que você para de digitar.
- **Status:** Confirmado, Atualizado, Provisório, Candidato ou Encerrado.
- **Idade:** Novo (até 7 dias do ajuizamento), Recente (8 a 30 dias) ou Histórico (mais de 30 dias).
- **Prioridade:** Urgente, Alta, Média ou Monitoramento.
- **UF:** estado do tribunal.

Os filtros se combinam. Acima da tabela aparece o total de processos; se houver mais de 300, a tela mostra "Exibindo 300 de N processos" e pede para refinar.

**Atenção:** a busca por CNPJ ou razão social só encontra processos que já têm empresa vinculada. Se não achar, tente pelo número do processo ou pelo nome da parte.

### 4.3 Colunas da tabela

| Coluna | O que mostra |
| --- | --- |
| Partes e CNPJ | Empresa vinculada com CNPJ. Sem empresa, mostra o requerente e o requerido vindos das publicações e o aviso "CNPJ pendente". Sem nenhuma parte, "Partes não identificadas" |
| Evento e estágio | Tipo do evento (por exemplo, Pedido de RJ) e o estágio atual (por exemplo, Distribuído, aguardando decisão) |
| Datas e latência | Data de ajuizamento, há quantos dias o pedido foi descoberto e uma barra: a parte clara vai do ajuizamento até a disponibilização na fonte; a parte escura, da fonte até a descoberta pelo sistema |
| Tribunal e processo | Número CNJ, tribunal e vara |
| Confiança | Percentual de confiança da classificação e quantas divergências existem |
| Prioridade | Nível de prioridade, com um marcador colorido |
| Status | Selo do status e, abaixo, "contato bloqueado" quando a abordagem ainda não é permitida |

Clique em qualquer linha para abrir o detalhe do processo.

### 4.4 Significado das prioridades

| Prioridade | Quando |
| --- | --- |
| Urgente | Ajuizado há até 1 dia |
| Alta | Ajuizado há até 7 dias, ou até 30 dias ainda aguardando decisão ou já deferido |
| Média | 8 a 30 dias em outros estágios, ou deferido há até 90 dias |
| Monitoramento | Casos antigos, encerrados ou fora da camada de RJ |

Grupos com mais de uma empresa recuperanda sobem um nível.

### 4.5 Exportar confirmadas (CSV)

O botão no canto superior direito baixa uma planilha (separada por ponto e vírgula) com as RJs confirmadas. Empresas com opt out não saem na planilha, e sinais preventivos nunca são exportados. Disponível para admin e analista; cada exportação fica registrada.

## 5. Detalhe do processo

Ao clicar em uma linha, abre um painel lateral com tudo o que o sistema sabe sobre o processo. Feche com o botão **Fechar**, com a tecla Esc ou clicando fora do painel.

### 5.1 Cabeçalho

- **Selo de status:** Confirmado, Atualizado, Provisório, Candidato, Encerrado ou Descartado.
- **Título:** o tipo de evento (por exemplo, Pedido de RJ ou Processamento deferido).
- **Número CNJ e tribunal.**
- **Divergências:** quadro tracejado com os motivos de dúvida (por exemplo, "distribuição por dependência"), quando houver.

### 5.2 Partes

Mostra as partes agrupadas em Polo ativo (requerente), Polo passivo (requerido) e Outros (advogados, com OAB). Ao lado de cada nome aparece a origem (DJEN ou MANUAL) e o link "fonte".

**Incluir parte** (admin e analista), quando o DJEN ainda não trouxe as partes:

1. Abra a consulta do processo no site do tribunal.
2. Clique em **Incluir parte** para abrir o formulário.
3. Preencha **Nome**, **Polo** (ativo, passivo ou outros) e **Tipo** (parte ou advogado).
4. Se for advogado, preencha **OAB** no formato `12345/PE`.
5. Em **URL da consulta processual**, cole o endereço da página do tribunal. O campo é obrigatório.
6. Clique em **Incluir parte**.

Incluir uma parte não libera o contato comercial; para isso é preciso vincular o CNPJ (item 5.3).

### 5.3 Empresa

Mostra a empresa vinculada: razão social, CNPJ, raiz do CNPJ, papel (requerente ou litisconsorte), município, UF, porte, CNAE, situação cadastral e outros nomes. Sem empresa, aparece o aviso de que a identidade está pendente e o contato bloqueado.

**Vincular identidade** (admin e analista):

1. Clique em **Vincular identidade**.
2. Digite o **CNPJ**.
3. Clique em **Consultar cadastro** para conferir razão social, cidade e situação na Receita.
4. Escolha o **Papel**: Requerente ou Litisconsorte.
5. Em **URL da evidência**, cole o link da capa, petição inicial, decisão ou publicação que comprova que aquela empresa é a requerente. É obrigatório.
6. Clique em **Vincular**.

O sistema recalcula confiança, prioridade e contato na hora e fecha a revisão de identidade.

### 5.4 Processo

| Campo | O que mostra |
| --- | --- |
| Evento e estágio | Tipo do evento e estágio atual |
| Classe | Código e nome da classe processual (129 é Recuperação Judicial) |
| Assuntos | Assuntos cadastrados pelo tribunal |
| Órgão julgador | Vara e comarca |
| Ajuizamento | Data e hora do pedido e a idade (Novo, Recente ou Histórico) |
| Disponível na fonte | Quando o processo apareceu no DataJud |
| Descoberta | Quando o sistema encontrou o processo e quantos dias depois do ajuizamento |
| Administrador judicial | Nome, quando lido em publicação de nomeação |
| Confiança | Percentual e rota da decisão (A, C ou D) |
| Prioridade | Nível de prioridade |
| Fonte oficial | Link para a consulta pública do tribunal (hoje só para o TJSP) |
| Versões | Versão das regras e da TPU usadas na classificação |

### 5.5 Motivos, evidências e movimentos

- **Motivos da classificação:** por que o sistema chegou a essa conclusão, em frases.
- **Evidências:** cada prova com nível (A a D), fonte, tipo, resumo e data de coleta. Evidências geradas por IA são marcadas e nunca são primárias.
- **Movimentos relevantes:** andamentos que importam para a RJ, com código e data. "Indício, confirmar em documento" indica movimento genérico.

### 5.6 Oportunidade

Aparece só para RJ confirmada e ativa. Mostra a etapa do funil, o responsável e o motivo de encerramento, quando houver. Perfis admin e comercial podem editar:

- **Responsável:** quem cuida da oportunidade.
- **Etapa:** Nova, Em análise, Contato autorizado, Contatada, Proposta, Ganha, Perdida ou Encerrada.
- **Registro de contato:** anotação do contato feito.
- **Salvar funil:** grava e registra no histórico.

Com o contato bloqueado, as etapas Contato autorizado, Contatada e Proposta são recusadas, e a tela avisa.

### 5.7 Revisões, histórico e correção

- **Revisões:** itens abertos ou decididos para o processo, com fila, decisão, revisor e justificativa.
- **Histórico de alterações:** cada mudança de status, estágio, tipo, prioridade ou vara, com data, valor anterior e novo.
- **Correção** (todos os perfis): escolha o **Tipo** (Duplicidade, Erro de classificação, Encerramento, Identidade incorreta ou Contestação da empresa), descreva e clique em **Registrar correção**. O caso vai para a Revisão humana.

## 6. Falência e extrajudicial

Mostra, separados das RJs, os pedidos de falência e as recuperações extrajudiciais. Nenhum deles conta como nova recuperação judicial.

- **Pedido de falência:** sinal relevante para a camada preventiva, não é RJ. Quando a empresa tem CNPJ vinculado, vira automaticamente o sinal "Pedido de falência ativo" no Preventivo.
- **Recuperação extrajudicial:** acordo com credores homologado em juízo, classificado à parte.

Cards, busca, filtros, colunas, rolagem e detalhe funcionam exatamente como na tela Novas recuperações (seções 4 e 5). O botão de exportação não aparece aqui.

## 7. Revisão humana

Aqui ficam os casos em que o sistema não decide sozinho. Cada decisão exige uma justificativa de pelo menos 10 caracteres e fica registrada com seu nome.

**Filas** (botões no topo):

| Fila | O que entra | Botões de decisão |
| --- | --- | --- |
| Classificação | Processos com divergência, provisórios, candidatos e correções pedidas | Confirmar, Descartar, Manter provisório |
| Identidade | RJs sem CNPJ verificado, ou com CNPJ encontrado sem papel claro | Descartar processo, Anotar e manter |
| Preventivo | Empresas com score de risco elevado ou prioridade de análise | Aprovar alerta, Rejeitar |

**Cada item mostra:** número CNJ (clique para abrir o detalhe), tribunal, vara, o motivo da revisão, a data de abertura e a data de ajuizamento. O topo da lista informa quantos itens estão pendentes; são exibidos até 300.

**Como decidir:**

1. Abra o processo e confira as evidências.
2. Escreva a justificativa no campo "Justificativa (obrigatória)".
3. Clique no botão da decisão.

**O que cada decisão faz:**

- **Confirmar:** o provisório passa a Confirmado.
- **Descartar:** o processo sai das listas. Na fila Identidade, descarta o processo inteiro.
- **Manter provisório / Anotar e manter:** grava a observação e deixa o item aberto.
- **Aprovar alerta:** libera o alerta preventivo para quem optou por receber.
- **Rejeitar:** não dispara alerta.

Na fila Identidade, a forma normal de resolver é vincular o CNPJ no detalhe do processo (seção 5.3); o item se fecha sozinho. A decisão humana prevalece nas coletas seguintes.

## 8. Preventivo

Mostra empresas com sinais de que podem vir a pedir recuperação judicial. É um indicador para priorizar análise, não uma previsão, e nunca pode ser divulgado como lista. Visível para admin e analista; cada acesso fica registrado.

**Faixa de aviso no topo:** "Recuperação judicial não confirmada". A linguagem externa permitida é "sinais públicos indicam necessidade de análise".

**Cada empresa mostra:**

- **Selo listrado** com o score em pontos (0 a 100).
- **Razão social e CNPJ.**
- **Faixa:** Monitoramento (0 a 24), Atenção (25 a 49), Risco elevado (50 a 69) ou Prioridade de análise humana (70 a 100).
- **Revisado ou aguardando revisão.**
- **"Já possui RJ confirmada"**, quando for o caso.
- **Fatores:** cada sinal com os pontos, a descrição, a fonte e, se não contar, o motivo (expirado, sem fonte ou sem data).
- **Salvaguarda:** aviso quando o score foi limitado a 49 por falta de fontes confiáveis.

### Registrar sinal

| Campo | Como preencher |
| --- | --- |
| CNPJ | CNPJ da empresa |
| Tipo | Um dos sinais do catálogo; a lista mostra o peso e a validade em dias. Os negativos (quitação, extinção do pedido de falência, esclarecimento oficial) reduzem o score |
| Nível da fonte | A: documento do próprio processo; B: fonte oficial; C: provedor licenciado; D: notícia ou menção |
| Fonte | Nome da fonte (obrigatório) |
| URL | Link da fonte (obrigatório) |
| Data do sinal | Quando o fato aconteceu; define a validade |
| Descrição | Resumo do sinal |

Clique em **Registrar**. Sinais de nível D valem no máximo 3 pontos. Score em Risco elevado ou acima abre um item na Revisão humana, fila Preventivo.

## 9. Alertas

Lista os 200 alertas mais recentes gerados pelo sistema, do mais novo para o mais antigo. Alertas preventivos só aparecem para admin e analista.

| Selo | Quando aparece |
| --- | --- |
| Confirmado | Nova recuperação judicial identificada em fonte oficial |
| Atualização | Uma RJ já confirmada mudou de estágio ou de tipo |
| Preventivo | Sinal preventivo aprovado em revisão |
| Correção | Um alerta anterior foi corrigido (a RJ foi rebaixada ou descartada) |

**Cada alerta mostra:** o selo, o assunto (por exemplo, "Nova recuperação judicial identificada | empresa | UF"), o resumo, a data, a próxima ação sugerida e o link **abrir processo**.

Os mesmos alertas são enviados por e-mail, webhook, Slack ou Teams para quem configurou em Preferências.

## 10. Fontes e saúde

Mostra se cada fonte está funcionando em cada tribunal. Falha de fonte nunca significa que não há processo: significa que o sistema ainda não conseguiu consultar.

### 10.1 Cards de saúde

Um card por fonte e tribunal (por exemplo, "DataJud TJSP" ou "DJEN NACIONAL"), com:

- **Status:** operando (OK), parcial, indisponível ou interrompido por mudança de esquema.
- **Último sucesso:** data e hora da última consulta concluída.
- **Erro:** o motivo da falha, quando houver.
- **Registros e tempo:** quantos registros vieram e quanto a consulta levou, em milissegundos.

| Status | O que significa | Precisa de ação? |
| --- | --- | --- |
| Operando | Última coleta concluída | Não |
| Parcial | O tempo da execução acabou; a próxima continua de onde parou | Não |
| Indisponível | A fonte não respondeu ou recusou o acesso | Se persistir, avisar a equipe técnica |
| Interrompido por esquema | A fonte mudou o formato dos dados | Sim, avisar a equipe técnica |

### 10.2 Outros blocos

- **Dicionário TPU:** versão vigente das tabelas do CNJ e o início do hash que a identifica.
- **Cursores incrementais:** até que data cada tribunal já foi lido. A próxima coleta relê as últimas 72 horas por segurança.
- **Execuções recentes:** as 20 últimas execuções, com tipo, início e fim.

### 10.3 Botões (só administrador)

| Botão | O que faz | Tempo |
| --- | --- | --- |
| Sincronizar TPU | Confere no CNJ os códigos de classes, assuntos e movimentos usados pelas regras e grava nova versão se algo mudou | Segundos |
| Buscar partes no DJEN | Consulta as publicações dos processos que ainda não têm partes ou publicação; mostra quantos processos consultou e quantas partes novas achou | Até alguns minutos |
| Executar coleta agora | Busca no DataJud os processos atualizados, em 5 lotes ("Coletando lote 1 de 5"), cobrindo os 27 TJs | Cerca de 4 minutos |

A coleta também roda sozinha a cada 10 minutos. Use os botões para antecipar, por exemplo logo depois de uma instalação.

## 11. Métricas

Mostra a qualidade do sistema medida sobre a operação real. Um card sem número aparece como "sem dados" até haver informação suficiente.

| Card | O que mede | Meta | Quando passa a ter valor |
| --- | --- | --- | --- |
| Cobertura confirmada | Quantas RJs de uma amostra oficial conhecida o sistema encontrou | 95% ou mais | Depois que o administrador carrega a amostra de controle |
| Precisão confirmada | Quantos confirmados não foram descartados na revisão humana | 98% ou mais | Depois das primeiras decisões na Revisão humana |
| Latência na fonte (P50 e P95) | Horas entre o processo aparecer no DataJud e o sistema descobri-lo | P50 até 2 h; P95 até 24 h | Depois da primeira coleta incremental |
| Atraso judicial médio | Dias entre o ajuizamento e a descoberta, incluindo o atraso dos tribunais | Informativo | Com pedidos novos ou recentes |
| Deduplicação | Quanto a base está livre de duplicidades apontadas | 99% ou mais | Com processos na base |
| Rastreabilidade | Alertas que têm fonte, evidência e versão da regra | 100% | Depois do primeiro alerta |

As barras sob os cards mostram o percentual. Abaixo, o bloco **Distribuição** mostra quantos processos há por status, por tipo de evento e quantas revisões estão pendentes em cada fila.

P50 é o valor do meio (metade dos casos fica abaixo dele) e P95 é o valor abaixo do qual ficam 95% dos casos.

## 12. Preferências de alerta

Define quais alertas você recebe fora do painel e por qual canal. No painel, os alertas aparecem sempre. Sem nenhum canal preenchido, você não recebe nada fora do painel.

| Campo | Como preencher | Vazio significa |
| --- | --- | --- |
| Tribunais | Siglas separadas por vírgula, por exemplo `TJSP, TJRJ` | Todos |
| UFs | Siglas separadas por vírgula, por exemplo `SP, RJ, MG` | Todas |
| Eventos | Tipos separados por vírgula, por exemplo `RJ_PEDIDO_NOVO, RJ_PROCESSAMENTO_DEFERIDO` | Todos |
| Canais | `email`, `webhook`, `slack` e/ou `teams`, separados por vírgula | Nenhum envio externo |
| Frequência | Imediata ou Resumo diário | Imediata |
| E-mail | Seu endereço, se usar o canal email |  |
| Webhook | Endereço que recebe o alerta em JSON |  |
| Slack | Endereço de incoming webhook do canal |  |
| Teams | Endereço de incoming webhook do canal |  |
| Receber alertas preventivos revisados | Marque para receber preventivos aprovados (só admin e analista) | Não recebe |

Clique em **Salvar**. Alertas de correção sempre chegam a quem recebeu o alerta original, mesmo fora do filtro de eventos.

**Tipos de evento que podem ser filtrados:** RJ\_PEDIDO\_NOVO, RJ\_TUTELA\_ANTECEDENTE, RJ\_PROCESSAMENTO\_DEFERIDO, RJ\_PROCESSAMENTO\_INDEFERIDO, RJ\_PLANO\_APRESENTADO, RJ\_CONCEDIDA e RJ\_FALENCIA.

**Aviso:** a opção Resumo diário ainda não envia e-mail; os alertas ficam guardados aguardando um envio que não está agendado. Use Imediata por enquanto.

## 13. Usuários

Tela exclusiva do administrador para incluir, excluir e gerar senhas. Toda alteração fica na auditoria.

### 13.1 Incluir usuário

| Campo | Como preencher |
| --- | --- |
| Nome | Nome completo da pessoa |
| Login | De 3 a 60 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado. Sugestão: `nome.sobrenome` |
| Perfil | Administrador, Analista, Comercial ou Leitor (padrão: Leitor) |
| Senha | Deixe vazio para o sistema gerar uma senha de 12 caracteres, ou digite uma com pelo menos 8 |

Clique em **Incluir usuário**. A senha aparece uma única vez num quadro, com o botão **Copiar senha**. Envie-a à pessoa por um canal seguro.

### 13.2 Usuários cadastrados

Cada usuário aparece com nome, login, perfil e a data de cadastro, e dois botões:

- **Gerar nova senha:** pede confirmação, cria uma senha nova e a mostra uma vez. A senha anterior deixa de funcionar e a pessoa é desconectada na hora.
- **Excluir:** pede confirmação e remove o usuário e suas preferências. A ação não pode ser desfeita. Não aparece para o seu próprio usuário.

**Regras:** não é possível excluir a si mesmo nem o último administrador. Para trocar o perfil de alguém, exclua e inclua de novo com o perfil certo.

## 14. Glossário e perguntas frequentes

### 14.1 Glossário

| Termo | Significado |
| --- | --- |
| RJ | Recuperação judicial (Lei 11.101/2005) |
| Número CNJ | Número único do processo no padrão NNNNNNN-DD.AAAA.J.TR.OOOO |
| DataJud | Base pública do CNJ com os dados dos processos de todo o país; não traz partes |
| DJEN | Diário de Justiça Eletrônico Nacional: publicações oficiais, com partes e advogados |
| TPU | Tabelas Processuais Unificadas do CNJ: códigos de classes, assuntos e movimentos |
| Classe 129 | Código da classe Recuperação Judicial |
| Ajuizamento | Data em que o pedido foi protocolado |
| Descoberta | Data em que o Antevê encontrou o processo |
| Estágio | Momento do processo: distribuído, deferido, concedido, encerrado etc. |
| Polo ativo / passivo | Quem pede (requerente) e contra quem se pede (requerido) |
| Evidência | Prova que sustenta uma informação, com fonte e link; nível A (mais forte) a D (mais fraca) |
| Confiança | Percentual que indica o quanto a classificação está apoiada em fonte oficial |
| Contato bloqueado | A empresa ainda não pode ser abordada comercialmente |
| Opt out | Pedido da empresa para não ser contatada |
| Score preventivo | Pontuação de 0 a 100 de sinais de risco; não confirma RJ |

### 14.2 Perguntas frequentes

**Por que quase todos os processos mostram "CNPJ pendente" e "contato bloqueado"?** O DataJud não informa partes nem CNPJ. A identidade vem do DJEN ou do vínculo manual pelo analista (seção 5.3).

**Busquei uma empresa pelo CNPJ e não achei. Ela não está em RJ?** Não dá para concluir isso. A busca por CNPJ só encontra processos com empresa já vinculada. Tente pelo número do processo ou pelo nome da parte. Além disso, a base cobre pedidos ajuizados nos últimos 12 meses.

**Um pedido novo demora quanto para aparecer?** O sistema consulta a fonte a cada 10 minutos, mas os tribunais levam em média cerca de 24 dias para enviar o processo ao DataJud.

**Qual a diferença entre Provisório e Confirmado?** Confirmado tem fonte oficial sem divergência. Provisório tem alguma dúvida, como assunto divergente ou distribuição por dependência, e precisa de revisão antes de qualquer oferta.

**Posso divulgar a lista do Preventivo?** Não. O score é de uso interno, não é exportado e nunca pode ser publicado como lista.

**Um processo está classificado errado. O que faço?** Abra o detalhe e use o bloco Correção. O caso vai para a Revisão humana.

**Uma empresa pediu para não ser contatada.** Registre o opt out com o administrador. Hoje o registro é feito pela equipe técnica, porque ainda não há botão no painel.

**A tela voltou para o login sozinha.** A sessão dura 12 horas e é encerrada se sua senha for trocada. Entre de novo.
