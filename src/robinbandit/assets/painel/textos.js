/* Textos do painel, com idiomas lado a lado para facilitar revisão. */
const TEXTOS = {
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

  /* --- tela: agora --- */
  'agora.titulo': { pt: 'O que está acontecendo', en: 'What is happening' },
  'agora.intro': {
    pt: 'Veja a saúde de quem está disponível, qual modo está ativo e por que a fila ficou nesta ordem.',
    en: 'See who is available, which mode is active, and why the queue is in this order.'
  },
  'agora.fila':      { pt: 'A fila de agora',    en: 'The queue right now' },
  'agora.atividade': { pt: 'Atividade recente',  en: 'Recent activity' },
  'agora.atividade_nota': {
    pt: 'Só metadados operacionais desta execução. Conversas não são guardadas aqui.',
    en: 'Operational metadata from this run only. Conversations are not stored here.'
  },
  'agora.credito':   { pt: 'Crédito restante',   en: 'Credit left' },
  'agora.30dias':    { pt: 'Últimos 30 dias',    en: 'Last 30 days' },
  'agora.sem_hist':  { pt: 'sem histórico ainda', en: 'no history yet' },

  /* --- tela: provedores --- */
  'prov.titulo': { pt: 'Provedores e rota', en: 'Providers and route' },
  'prov.intro': {
    pt: 'Escolha a política da fila. Os provedores disponíveis continuam protegidos por saúde e cooldown em todos os modos.',
    en: 'Choose the queue policy. Available providers remain protected by health and cooldown in every mode.'
  },
  'prov.como_decidir': { pt: 'Como a rota normal decide', en: 'How the normal route decides' },
  'prov.rota_padrao': { pt: 'padrão', en: 'default' },
  'prov.rota_opcional': { pt: 'por chamada', en: 'per request' },
  'prov.normal': { pt: 'Normal', en: 'Normal' },
  'prov.reforcado': { pt: 'Reforçado', en: 'Reinforced' },
  'prov.ou': { pt: 'ou', en: 'or' },
  'prov.normal_desc': {
    pt: 'Toda chamada entra aqui. Você escolhe abaixo como ordenar a fila.',
    en: 'Every request enters here. Choose below how the queue should be ordered.'
  },
  'prov.reforcado_desc': {
    pt: 'Tenta sua lista preferida e, se ela falhar, volta para a rota normal.',
    en: 'Tries your preferred list and returns to the normal route if it fails.'
  },
  'prov.normal_header': {
    pt: 'Esta é a rota padrão, usada sem header ou com',
    en: 'This is the default route, used without a header or with'
  },
  'prov.modo.adaptive': { pt: 'Adaptativo', en: 'Adaptive' },
  'prov.modo.tier': { pt: 'Prioridade por tier', en: 'Tier priority' },
  'prov.modo.fixed': { pt: 'Lista fixa', en: 'Fixed list' },
  'prov.modo.round_robin': { pt: 'Rodízio', en: 'Round robin' },
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
    pt: 'Se todos falharem, ninguém assume o lugar deles: o RobinBandit devolve um aviso dizendo que nenhum provedor respondeu. Isso não é um provedor de reserva, e por isso não aparece em nenhum tier.',
    en: 'If they all fail, nobody takes their place: RobinBandit returns a notice saying no provider answered. That is not a backup provider, which is why it shows up in no tier.'
  },

  /* --- tela: modelos --- */
  'mod.titulo': { pt: 'Modelos de cada provedor', en: "Each provider's models" },
  'mod.intro': {
    pt: 'Quando o RobinBandit escolhe um provedor, ele tenta os modelos desta lista de cima para baixo, e para no primeiro que responder. Acrescente um modelo pelo id, ou pergunte ao provedor o que ele tem hoje.',
    en: 'Once RobinBandit picks a provider, it tries the models on this list top-down and stops at the first one that answers. Add a model by id, or ask the provider what it has today.'
  },

  /* --- tela: credenciais --- */
  'cred.titulo': { pt: 'Contas e credenciais', en: 'Accounts and credentials' },
  'cred.intro': {
    pt: 'A chave que você colar aqui vai para o cofre desta máquina, com permissão 0600. Ela nunca volta na resposta, nem mesmo parcialmente. Um provedor pode ter mais de uma conta, e o rotador alterna entre elas quando uma bate a cota.',
    en: 'A key pasted here goes into this machine’s vault with 0600 permissions. It never comes back in a response, even partially. A provider can have more than one account, and the rotator alternates between them when one hits its quota.'
  },
  'cred.so_ambiente': { pt: 'Chaves que estão só no ambiente', en: 'Keys that live only in the environment' },
  'cred.copie_1': {
    pt: 'Copie para o cofre do RobinBandit e ele deixa de depender do',
    en: 'Copy them into RobinBandit’s vault and it stops depending on the'
  },
  'cred.copie_2': {
    pt: 'do projeto que o hospeda. O arquivo de origem não é tocado, e o que já está no cofre fica como está.',
    en: 'of the project hosting it. The source file is not touched, and what is already in the vault stays as it is.'
  },
  'cred.trazer':     { pt: 'trazer para o cofre',   en: 'bring into the vault' },
  'cred.add_conta':  { pt: 'Adicionar outra conta', en: 'Add another account' },
  'cred.add_intro': {
    pt: 'Mesma conta do provedor com outra chave, ou uma segunda conta sua. A chave é guardada pelo nome de variável que você escolher.',
    en: 'The same provider account with another key, or a second account of yours. The key is stored under the variable name you choose.'
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
    pt: 'Assinatura não fica lenta quando o uso acaba: ela para e volta numa hora previsível. Veja quanto falta para decidir entre esperar e trocar de provedor.',
    en: 'A subscription does not get slow when usage runs out: it stops and returns at a predictable time. See how long remains before choosing whether to wait or switch providers.'
  },

  /* --- tela: uso --- */
  'uso.titulo': { pt: 'Uso e custo', en: 'Usage and cost' },
  'uso.intro': {
    pt: 'Acompanhe chamadas, tokens de entrada e saída e o custo informado pelo provedor.',
    en: 'Track calls, input and output tokens, and costs reported by the provider.'
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
    pt: 'Qualquer ferramenta que deixe trocar o endereço da API passa a rotear por aqui. Copie a configuração da sua e cole onde ela indica. No campo',
    en: 'Any tool that lets you change the API address starts routing through here. Copy the configuration for yours and paste it where it says. In the'
  },
  'con.intro_2': {
    pt: 'vai um apelido do seu trabalho, como "codigo" ou "revisao". O RobinBandit aprende separado para cada um.',
    en: 'field goes a nickname for your work, such as "code" or "review". RobinBandit learns separately for each one.'
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
    pt: 'O login do Claude Code e do ChatGPT Codex permite que eles respondam. Para rotear chamadas, ainda falta configurar um cliente na aba Conectar.',
    en: 'Claude Code and ChatGPT Codex login lets them answer. To route calls, configure a client in the Connect tab.'
  },
  'inicio.p2.feito': {
    pt: '{quem} já chamou. A fila abaixo passa a mostrar as decisões.',
    en: '{quem} has called through. The queue below starts showing the decisions.'
  },
  'inicio.p3.titulo': { pt: 'Faça uma chamada', en: 'Make one call' },
  'inicio.p3.texto': {
    pt: 'A partir da primeira chamada, esta tela mostra quem está na frente e por quê. Antes disso não há o que mostrar.',
    en: 'From the first call on, this screen shows who is ahead and why. Before that there is nothing to show.'
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
