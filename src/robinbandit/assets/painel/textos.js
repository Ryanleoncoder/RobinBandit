/* As duas línguas em que o painel fala.
 *
 * A documentação virou bilíngue e a página do projeto está em inglês; quem
 * chegasse por lá instalava e encontrava a interface em português. O código e
 * os comentários continuam em português — isto é sobre o que o produto
 * responde, não sobre quem o mantém.
 *
 * Um arquivo só, com as duas línguas lado a lado: separar em `pt.js` e `en.js`
 * faria a tradução faltante virar arquivo silenciosamente incompleto, e aqui
 * uma chave sem par salta aos olhos na revisão.
 *
 * Acrescentar um idioma é acrescentar uma chave em cada entrada e o código em
 * `IDIOMAS` do `idioma.py`.
 */
const TEXTOS = {
  /* --- navegação --- */
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
    pt: 'A fila de agora e o motivo dela. Quem decide é o bandit: qualidade e saúde são posteriores Beta, e o sorteio é o que o faz continuar explorando em vez de travar no primeiro que deu certo.',
    en: 'The queue right now, and the reason for it. The bandit decides: quality and health are Beta posteriors, and the draw is what keeps it exploring instead of locking onto the first thing that worked.'
  },
  'agora.fila':      { pt: 'A fila de agora',    en: 'The queue right now' },
  'agora.credito':   { pt: 'Crédito restante',   en: 'Credit left' },
  'agora.30dias':    { pt: 'Últimos 30 dias',    en: 'Last 30 days' },
  'agora.sem_hist':  { pt: 'sem histórico ainda', en: 'no history yet' },

  /* --- tela: provedores --- */
  'prov.titulo': { pt: 'Provedores por tier', en: 'Providers by tier' },
  'prov.intro': {
    pt: 'Tier é um grupo, e vários provedores cabem no mesmo. Arraste para mudar de grupo; o botão tira e devolve à cadeia. O que o tier significa na hora de decidir depende da escolha abaixo.',
    en: 'A tier is a group, and several providers fit in the same one. Drag to change group; the button removes a provider from the chain and puts it back. What the tier means at decision time depends on the choice below.'
  },
  'prov.como_decidir': { pt: 'Como decidir', en: 'How to decide' },
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
    pt: 'A chave que você colar aqui vai para o cofre desta máquina, com permissão 0600, e nunca volta na resposta — nem o começo, nem o fim. Um provedor pode ter mais de uma conta, e o rotador alterna entre elas quando uma bate a cota.',
    en: 'A key pasted here goes into this machine’s vault with 0600 permissions, and never comes back in a response — not the start of it, not the end. A provider can have more than one account, and the rotator alternates between them when one hits its quota.'
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
    pt: 'Mesma conta do provedor com outra chave, ou uma segunda conta sua. O nome da variável é escolha sua — é por ele que a chave é guardada.',
    en: 'The same provider account with another key, or a second account of yours. The variable name is your call — it is what the key is stored under.'
  },
  'cred.paga':       { pt: 'crédito pago', en: 'paid credit' },
  'cred.criar':      { pt: 'criar conta',  en: 'create account' },
  'cred.apelido':    { pt: 'apelido, ex.: groq-2', en: 'label, e.g. groq-2' },

  /* --- tela: janelas --- */
  'jan.titulo': { pt: 'Janelas de assinatura', en: 'Subscription windows' },
  'jan.intro': {
    pt: 'Assinatura não fica lenta quando o uso acaba: ela para, e volta numa hora que dá para saber. Aqui está quanto falta para o bloco de cada uma virar — o suficiente para decidir entre esperar e trocar de provedor.',
    en: 'A subscription does not get slow when usage runs out: it stops, and comes back at a knowable time. Here is how long until each block turns over — enough to decide between waiting and switching providers.'
  },

  /* --- tela: uso --- */
  'uso.titulo': { pt: 'Tokens gastos', en: 'Tokens spent' },
  'uso.intro': {
    pt: 'Cada provedor já informa quanto custou a resposta, e esse número era usado para decidir dentro do turno e descartado em seguida. Aqui ele fica: um quadrado por dia, mais escuro nos dias em que você gastou mais.',
    en: 'Every provider already reports what a response cost, and that number used to be read within the turn and thrown away. Here it stays: one square per day, darker on the days you spent more.'
  },
  'uso.ano':         { pt: 'Seu ano',          en: 'Your year' },
  'uso.por_provedor': { pt: 'Abrir por provedor', en: 'Break down by provider' },
  'uso.moeda': {
    pt: 'Em tokens, não em reais: preço muda por modelo, por região e por promoção, e um custo calculado com tabela velha dá a confiança de um número exato sobre um palpite desatualizado.',
    en: 'In tokens, not currency: prices change by model, by region and by promotion, and a cost computed from a stale table lends the confidence of an exact number to an out-of-date guess.'
  },

  /* --- tela: conectar --- */
  'con.titulo': { pt: 'Plugar uma ferramenta', en: 'Plug in a tool' },
  'con.intro_1': {
    pt: 'Qualquer ferramenta que deixe trocar o endereço da API passa a rotear por aqui. Copie a configuração da sua e cole onde ela indica. No campo',
    en: 'Any tool that lets you change the API address starts routing through here. Copy the configuration for yours and paste it where it says. In the'
  },
  'con.intro_2': {
    pt: 'vai um apelido do seu trabalho — "codigo", "revisao" — e o RobinBandit aprende separado para cada um.',
    en: 'field goes a nickname for your work — "code", "review" — and RobinBandit learns separately for each one.'
  },

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

/* O idioma que o servidor diz estar valendo. Fica aqui como padrão até a
 * primeira resposta de `config`; trocar sem recarregar a página é o mínimo que
 * se espera de um seletor de idioma. */
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

/* Aplica a tradução em tudo que está marcado no HTML. Chamado na carga e a cada
 * troca de idioma. */
function traduzirPagina() {
  document.querySelectorAll('[data-t]').forEach(el => {
    el.textContent = T(el.dataset.t);
  });
  document.querySelectorAll('[data-t-ph]').forEach(el => {
    el.placeholder = T(el.dataset.tPh);
  });
  document.documentElement.lang = IDIOMA === 'pt' ? 'pt-BR' : 'en';
}
