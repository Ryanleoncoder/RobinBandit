/* Textos do painel, com idiomas lado a lado para facilitar revisão. */
const TEXTOS = {
  'clf.rota': {pt:'Roteamento atual',en:'Current routing'},
  'clf.aba': {pt:'Classificador',en:'Classifier'},
  'clf.titulo': {pt:'Modelos por complexidade',en:'Models by complexity'},
  'clf.aviso': {pt:'O teste mostra a classificação sem chamar os modelos dos blocos.',en:'Testing shows the classification without calling box models.'},
  'clf.exemplo': {pt:'Carregar exemplo',en:'Load example'},
  'clf.salvar': {pt:'Salvar configuração',en:'Save configuration'},
  'clf.config_titulo': {pt:'Quem classifica',en:'Who classifies'},
  'clf.config_aviso': {pt:'Classificador especializado é a opção principal. LLM é uma alternativa; salvar não ativa o modo.',en:'A specialized classifier is the primary option. An LLM is an alternative; saving does not activate the mode.'},
  'clf.tipo': {pt:'Tipo',en:'Type'},
  'clf.nenhum': {pt:'Não escolhido',en:'Not selected'},
  'clf.llm': {pt:'LLM como alternativa',en:'LLM alternative'},
  'clf.workspace': {pt:'Configuração do classificador',en:'Classifier settings'},
  'prov.classificador_intro': {pt:'O classificador escolhe a complexidade. Cada bloco tenta os modelos na ordem que você definiu.',en:'The classifier selects the complexity. Each box tries models in your configured order.'},
  'clf.especializado': {pt:'Especializado (não conectado)',en:'Specialized (not connected)'},
  'clf.especializado_aviso': {pt:'Nenhum classificador especializado está conectado. O ambiente local permanece desativado.',en:'No specialized classifier is connected. The local runtime remains disabled.'},
  'clf.add_modelo': {pt:'Adicionar à classificação',en:'Add to classification'},
  'clf.provedor': {pt:'Provedor',en:'Provider'},
  'clf.modelo': {pt:'Modelo',en:'Model'},
  'clf.modelo_ph': {pt:'Escolha ou digite um ID',en:'Choose or enter an ID'},
  'clf.contexto': {pt:'Contexto enviado ao classificador',en:'Classifier context'},
  'clf.saida': {pt:'A saída aceita é apenas um rótulo de nível. Testar chama só as LLMs classificadoras.',en:'Only a level label is accepted as output. Testing calls only classifier LLMs.'},
  'clf.flash': {pt:'Para usar uma LLM, recomendamos começar por modelos Flash ou equivalentes leves. Compare o tempo e os acertos antes de escolher.',en:'For LLM classification, we recommend starting with Flash models or lightweight equivalents. Compare latency and accuracy before choosing.'},
  'clf.ordem': {pt:'Ordem dos classificadores',en:'Classifier order'},
  'clf.reservas': {pt:'O primeiro classifica. As reservas são tentadas se ele falhar ou devolver uma saída inválida.',en:'The first model classifies. Backups are tried if it fails or returns invalid output.'},
  'clf.editar': {pt:'Adicionar outro classificador',en:'Add another classifier'},
  'clf.pedido_teste': {pt:'Pedido para testar',en:'Test request'},
  'clf.contexto_teste': {pt:'Contexto adicional (opcional)',en:'Additional context (optional)'},
  'clf.testar': {pt:'Testar classificação',en:'Test classification'},
  'clf.teste_aviso': {pt:'Testa só o classificador. Pode consumir cota; não altera o modo ativo.',en:'Tests only the classifier. May consume quota; does not change the active mode.'},
  'clf.contextos_aviso': {pt:'O contexto de cada bloco descreve suas preferências para a LLM. Não cria regras por palavras nem muda a rota atual.',en:'Each box context describes your preferences for the LLM. It does not create keyword rules or change current routing.'},
  'clf.descartar': {pt:'Descartar alterações',en:'Discard changes'},
  'clf.centro': {pt:'Classificador',en:'Classifier'},
  'clf.desconectado': {pt:'Não escolhido',en:'Not selected'},
  'clf.nivel': {pt:'Apresentar nível',en:'Present level'},
  'clf.falha': {pt:'Simular falha do primeiro',en:'Simulate first model failure'},
  'clf.simular': {pt:'Apresentar fluxo',en:'Present flow'},
  'clf.ciclo': {pt:'Apresentar ciclo',en:'Present cycle'},
  'clf.parar': {pt:'Parar apresentação',en:'Stop presentation'},
  'clf.catalogo': {pt:'Modelos disponíveis',en:'Available models'},
  'clf.busca': {pt:'Buscar modelo ou provedor…',en:'Search model or provider…'},
  'clf.ajuda': {pt:'Arraste para o rosto ou uma caixa, ou clique para escolher o destino. Dentro de cada caixa, a tentativa segue da esquerda para a direita.',en:'Drop onto the face or a box, or click to choose a destination. Each box tries models from left to right.'},
  'clf.complexidade': {pt:'Destino',en:'Destination'},
  'clf.adicionar': {pt:'Adicionar',en:'Add'},
  'clf.cancelar': {pt:'Cancelar',en:'Cancel'},
  /* --- navegação --- */
  'nav.operar':      { pt: 'Operar',       en: 'Operate' },
  'nav.configurar':  { pt: 'Configurar',   en: 'Configure' },
  'nav.integrar':    { pt: 'Integrar',     en: 'Integrate' },
  'nav.agora':       { pt: 'Agora',       en: 'Now' },
  'nav.provedores':  { pt: 'Provedores',  en: 'Providers' },
  'nav.modelos':     { pt: 'Modelos',     en: 'Models' },
  'nav.credenciais': { pt: 'Credenciais', en: 'Credentials' },
  'nav.janelas':     { pt: 'Janelas',     en: 'Windows' },
  'nav.uso':         { pt: 'Uso',         en: 'Usage' },
  'nav.conectar':    { pt: 'Conectar',    en: 'Connect' },
  'busca.rotulo': { pt: 'Buscar no catálogo', en: 'Search the catalog' },

  /* --- tela: agora --- */
  'agora.titulo': { pt: 'O que está acontecendo', en: 'What is happening' },
  'agora.intro': {
    pt: 'Veja quem pode responder agora, quem está em espera e qual rota está em uso.',
    en: 'See who can answer now, who is waiting, and which route is in use.'
  },
  'agora.fila':      { pt: 'A fila de agora',    en: 'The queue right now' },
  'agora.atividade': { pt: 'Atividade recente',  en: 'Recent activity' },
  'agora.atividade_nota': {
    pt: 'Chamadas concluídas ficam no histórico local. Conversas não são guardadas aqui.',
    en: 'Completed calls are kept in local history. Conversations are not stored here.'
  },
  'agora.credito':   { pt: 'Crédito restante',   en: 'Credit left' },
  'agora.30dias':    { pt: 'Últimos 30 dias',    en: 'Last 30 days' },
  'agora.sem_hist':  { pt: 'sem histórico ainda', en: 'no history yet' },

  /* --- tela: provedores --- */
  'prov.titulo': { pt: 'Provedores e rota', en: 'Providers and route' },
  'prov.intro': {
    pt: 'Defina como a rota normal escolhe provedores e quando usar a fila Reforçada por chamada.',
    en: 'Set how the normal route chooses providers and when to use the Reinforced queue per request.'
  },
  'prov.como_decidir': { pt: 'Modo de roteamento', en: 'Routing mode' },
  'prov.rota_padrao': { pt: 'sempre ativa', en: 'always on' },
  'prov.rota_opcional': { pt: 'opcional', en: 'optional' },
  'prov.normal': { pt: 'Normal', en: 'Normal' },
  'prov.reforcado': { pt: 'Reforçado', en: 'Reinforced' },
  'prov.ou': { pt: 'ou', en: 'or' },
  'prov.normal_desc': {
    pt: 'Usada por padrão. Escolha abaixo se ela aprende, segue tiers, lista fixa ou rodízio.',
    en: 'Used by default. Choose below whether it learns, follows tiers, uses a fixed list, or rotates.'
  },
  'prov.reforcado_desc': {
    pt: 'Tenta contas preferidas primeiro. Se todas falharem, volta para a rota normal.',
    en: 'Tries preferred accounts first. If all fail, it returns to the normal route.'
  },
  'prov.normal_header': {
    pt: 'Usada sem header ou com',
    en: 'Used without a header or with'
  },
  'prov.modo.adaptive': { pt: 'Adaptativo', en: 'Adaptive' },
  'prov.modo.tier': { pt: 'Prioridade por tier', en: 'Tier priority' },
  'prov.modo.fixed': { pt: 'Lista fixa', en: 'Fixed list' },
  'prov.modo.round_robin': { pt: 'Rodízio', en: 'Round robin' },
  'prov.modo.classifier': { pt: 'Classificador', en: 'Classifier' },
  'prov.ordem': { pt: 'Ordem da cadeia', en: 'Chain order' },
  'prov.ordem.fixed': {
    pt: 'Esta é a ordem exata de tentativa. Use as setas para reorganizar.',
    en: 'This is the exact attempt order. Use the arrows to rearrange it.'
  },
  'prov.ordem.round_robin': {
    pt: 'O rodízio percorre este anel e avança depois de cada tentativa.',
    en: 'Round robin follows this ring and advances after each attempt.'
  },
  'prov.na_cadeia': { pt: 'Na sua cadeia', en: 'In your chain' },
  'prov.catalogo': { pt: 'Catálogo completo', en: 'Full catalog' },
  'prov.voltar_ordem': { pt: 'Voltar à ordem', en: 'Back to order' },
  'prov.vazio': {
    pt: 'Nenhum provedor na sua cadeia. Abra o catálogo para escolher.',
    en: 'No provider in your chain. Open the catalog to choose one.'
  },
  'prov.ultimo': {
    pt: 'Se todos falharem, o RobinBandit devolve um aviso. Esse aviso não é provedor e não entra em tier.',
    en: 'If everyone fails, RobinBandit returns a notice. That notice is not a provider and does not join a tier.'
  },

  /* --- tela: modelos --- */
  'mod.titulo': { pt: 'Modelos de cada provedor', en: "Each provider's models" },
  'mod.intro': {
    pt: 'Depois de escolher um provedor, o RobinBandit tenta estes modelos de cima para baixo. Adicione um id manualmente ou consulte o catálogo atual do provedor.',
    en: 'After choosing a provider, RobinBandit tries these models from top to bottom. Add an id manually or ask the provider for its current catalog.'
  },

  /* --- tela: credenciais --- */
  'cred.titulo': { pt: 'Contas e credenciais', en: 'Accounts and credentials' },
  'cred.intro': {
    pt: 'Chaves ficam no cofre local e nunca voltam na resposta. Você pode ter mais de uma conta por provedor e alternar quando uma bater a cota.',
    en: 'Keys stay in the local vault and never come back in responses. You can keep more than one account per provider and rotate when one hits quota.'
  },
  'cred.so_ambiente': { pt: 'Chaves que estão só no ambiente', en: 'Keys that live only in the environment' },
  'cred.copie_1': {
    pt: 'Copie para o cofre local para não depender do',
    en: 'Copy them into the local vault so it no longer depends on the'
  },
  'cred.copie_2': {
    pt: 'do projeto. O arquivo original não é alterado.',
    en: 'of the project. The original file is not changed.'
  },
  'cred.trazer':     { pt: 'trazer para o cofre',   en: 'bring into the vault' },
  'cred.add_conta':  { pt: 'Adicionar outra conta', en: 'Add another account' },
  'cred.add_intro': {
    pt: 'Use outra chave do mesmo provedor ou uma segunda conta sua. O nome da variável identifica essa conta.',
    en: 'Use another key from the same provider or a second account of yours. The variable name identifies that account.'
  },
  'cred.paga':       { pt: 'crédito pago', en: 'paid credit' },
  'cred.criar':      { pt: 'criar conta',  en: 'create account' },
  'cred.apelido':    { pt: 'apelido, ex.: groq-2', en: 'label, e.g. groq-2' },
  'cred.reforcado':    { pt: 'Reforçado', en: 'Reinforced' },
  'cred.ref_desc': {
    pt: 'Tenta estas contas na ordem antes da rota normal. Você pode misturar assinaturas, créditos e contas gratuitas.',
    en: 'Tries these accounts in order before the normal route. You can mix subscriptions, credits and free accounts.'
  },
  'cred.ref_header': {
    pt: 'Qualquer cliente HTTP pode pedir esta rota com',
    en: 'Any HTTP client can request this route with'
  },

  /* --- tela: janelas --- */
  'jan.titulo': { pt: 'Janelas de assinatura', en: 'Subscription windows' },
  'jan.intro': {
    pt: 'Veja quando uma assinatura volta a responder e decida se vale esperar ou seguir com outro provedor.',
    en: 'See when a subscription can answer again and decide whether to wait or move to another provider.'
  },

  /* --- tela: uso --- */
  'uso.titulo': { pt: 'Uso e custo', en: 'Usage and cost' },
  'uso.intro': {
    pt: 'Acompanhe chamadas, tokens de entrada, tokens de saída e custo quando o provedor informa.',
    en: 'Track calls, input tokens, output tokens, and cost when the provider reports it.'
  },
  'uso.ano':         { pt: 'Seu ano',          en: 'Your year' },
  'uso.por_provedor': { pt: 'Abrir por provedor', en: 'Break down by provider' },
  'uso.moeda': {
    pt: 'O custo só aparece quando o provedor o informa. Ausência de preço não significa uso grátis.',
    en: 'Cost only appears when the provider reports it. Missing pricing does not mean free usage.'
  },

  /* --- tela: conectar --- */
  'con.titulo': { pt: 'Plugar uma ferramenta', en: 'Plug in a tool' },
  'con.intro_1': {
    pt: 'Escolha sua ferramenta, copie a configuração e cole onde ela permite trocar a API. No campo',
    en: 'Choose your tool, copy the configuration, and paste it where it lets you change the API. In the'
  },
  'con.intro_2': {
    pt: 'use um apelido do trabalho, como "codigo" ou "revisao". O aprendizado fica separado por apelido.',
    en: 'field, use a work nickname such as "code" or "review". Learning stays separate per nickname.'
  },
  'con.copiar': { pt: 'Copiar', en: 'Copy' },
  'con.copiado': { pt: 'Copiado', en: 'Copied' },

  /* --- primeiros passos (so aparece antes da primeira chamada) --- */
  'inicio.titulo': {
    pt: 'Antes da primeira chamada',
    en: 'Before the first call'
  },
  'inicio.p1.titulo': { pt: 'Quem pode responder', en: 'Who can answer' },
  'inicio.p1.feito': {
    pt: '{quem} já estão disponíveis como provedores.',
    en: '{quem} are already available as providers.'
  },
  'inicio.p1.falta': {
    pt: 'Nenhum subiu. Cadastre uma chave em Credenciais, ou instale o Claude Code / Codex para usar pela assinatura.',
    en: 'None came up. Add a key under Credentials, or install Claude Code / Codex to use them through your subscription.'
  },
  'inicio.p2.titulo': { pt: 'Escolha quem envia os pedidos', en: 'Choose who sends requests' },
  'inicio.p2.texto': {
    pt: 'Claude Code e ChatGPT Codex podem responder quando seus CLIs estão logados. Para enviar chamadas ao RobinBandit, configure um cliente na aba Conectar.',
    en: 'Claude Code and ChatGPT Codex can answer when their CLIs are logged in. To send calls to RobinBandit, configure a client in the Connect tab.'
  },
  'inicio.p2.feito': {
    pt: '{quem} já chamou. A fila abaixo passa a mostrar as decisões.',
    en: '{quem} has called through. The queue below starts showing the decisions.'
  },
  'inicio.p3.titulo': { pt: 'Faça uma chamada', en: 'Make one call' },
  'inicio.p3.texto': {
    pt: 'Depois da primeira chamada, esta tela mostra a fila real, os motivos e os bloqueios.',
    en: 'After the first call, this screen shows the real queue, reasons, and blocks.'
  },
  'inicio.ir_conectar': { pt: 'Configurar um cliente', en: 'Configure a client' },

  /* --- comuns --- */
  'comum.lendo':      { pt: 'lendo…',      en: 'reading…' },
  'comum.carregando': { pt: 'carregando…', en: 'loading…' },
  'comum.consultando': { pt: 'consultando…', en: 'checking…' },
  'comum.idioma':     { pt: 'Idioma',      en: 'Language' },

  /* --- estados da fila (vêm do JS) --- */
  'selo.sem_uso':   { pt: 'sem uso',   en: 'idle' },
  'selo.saudavel':  { pt: 'saudável',  en: 'healthy' },
  'selo.instavel':  { pt: 'instável',  en: 'shaky' },
  'selo.falhando':  { pt: 'falhando',  en: 'failing' },
  'selo.espera':    { pt: 'em espera', en: 'waiting' },
  'selo.palpite':   { pt: 'palpite',   en: 'guess' },

  'tab.provedor':  { pt: 'Provedor',  en: 'Provider' },
  'tab.estado':    { pt: 'Estado',    en: 'State' },
  'tab.qualidade': { pt: 'Qualidade', en: 'Quality' },
  'tab.ok_erro':   { pt: 'OK / erro', en: 'OK / error' },
  'tab.latencia':  { pt: 'Latência',  en: 'Latency' },
  'tab.porque':    { pt: 'Por quê',   en: 'Why' },

  'fila.vazia': {
    pt: 'Nenhuma chamada ainda. A fila aparece depois do primeiro turno.',
    en: 'No calls yet. The queue shows up after the first turn.'
  },
  'fila.ninguem_espera': { pt: 'ninguém em espera', en: 'nobody waiting' },
  'fila.na_cadeia':      { pt: 'na cadeia',  en: 'in the chain' },
  'fila.chamadas':       { pt: 'chamadas',   en: 'calls' },
  'fila.fora_do_ar':     { pt: 'servidor fora do ar', en: 'server is down' },

  /* --- conexão (aba Conectar) --- */
  'con.nenhuma': {
    pt: '<b>Nenhuma chamada ainda.</b> Cole a configuração, use o agente uma vez e esta linha muda sozinha.',
    en: '<b>No calls yet.</b> Paste the configuration, use the agent once, and this line changes on its own.'
  },
  'con.conectado':   { pt: '<b>Conectado.</b> ',    en: '<b>Connected.</b> ' },
  'con.ja_conectou': { pt: '<b>Já conectou.</b> ',  en: '<b>Connected before.</b> ' },
  'con.uma_chamada': { pt: ' chamada, a última ',   en: ' call, the last one ' },
  'con.n_chamadas':  { pt: ' chamadas, a última ',  en: ' calls, the last one ' },
  'con.aprendendo':  { pt: ' Aprendendo em: ',      en: ' Learning in: ' },
  'tempo.agora':     { pt: 'agora',                 en: 'just now' },
  'tempo.min':       { pt: 'há {n} min',            en: '{n} min ago' },
  'tempo.h':         { pt: 'há {n}h',               en: '{n}h ago' }
};

/* Idioma inicial até a primeira resposta de `config`. */
let IDIOMA = 'pt';

function T(chave, campos) {
  const entrada = TEXTOS[chave];
  if (!entrada) return chave;          // faltando: aparece a chave, não quebra
  let texto = entrada[IDIOMA] || entrada.pt || chave;
  if (campos) {
    Object.keys(campos).forEach(k => {
      texto = texto.split('{' + k + '}').join(campos[k]);
    });
  }
  return texto;
}

/* Aplica tradução aos elementos marcados no HTML. */
function traduzirPagina() {
  document.querySelectorAll('[data-t]').forEach(el => {
    el.textContent = T(el.dataset.t);
  });
  document.querySelectorAll('[data-t-ph]').forEach(el => {
    el.placeholder = T(el.dataset.tPh);
  });
  document.documentElement.lang = IDIOMA === 'pt' ? 'pt-BR' : 'en';
}
