const $ = id => document.getElementById(id);
let config = null;
let ferramentas = [];
let estado = { provedores: [], ordem: [] };

function logo(nome) {
  const sigla = (nome || '?').slice(0, 2).toUpperCase();
  return '<img class="logo" src="logos/' + nome + '.svg" alt="" ' +
    'onerror="this.outerHTML=\'<span class=&quot;logo falta&quot;>' + sigla + '</span>\'">';
}

function selo(p) {
  // Deduzido do que a linha ja mostra, nao do `last_status` do processo: ele
  // nasce "idle" a cada restart, entao um provedor com 126 chamadas boas
  // recuperadas do aprendizado aparecia como "sem uso".
  if (p.cooldown) return ['mau', 'em espera'];
  const ok = p.ok || 0, err = p.err || 0, total = ok + err;
  if (!total) return ['', 'sem uso'];
  const taxa = ok / total;
  if (taxa >= 0.95) return ['bom', 'saudável'];
  if (taxa >= 0.7) return ['atencao', 'instável'];
  return ['mau', 'falhando'];
}

function medidor(valor, estimado) {
  // Sem historico o numero e o prior do catalogo — palpite de fabrica, igual
  // para todo mundo. Escrito igual a uma medicao, passava por uma.
  const n = Number(valor) || 0;
  const faixa = n >= 0.75 ? '' : n >= 0.5 ? ' medio' : ' baixo';
  return '<span class="medidor"><span class="trilho">' +
    '<span class="cheio' + faixa + '" style="width:' + Math.round(n * 100) + '%"></span></span>' +
    '<span class="valor' + (estimado ? ' palpite' : '') + '" title="' +
    (estimado ? 'palpite de fábrica: este provedor ainda não foi usado' : 'medido aqui') +
    '">' + (n ? n.toFixed(2) : '—') + '</span>' +
    (estimado && n ? '<span class="palpite-nota">palpite</span>' : '') + '</span>';
}

/* — Primeiros passos — */
/* So aparece antes da primeira chamada: passada ela, a fila em baixo responde
 * sozinha. Ate existir, quem instalava encontrava "nenhuma chamada ainda" — a
 * informacao estava certa e nao dizia o que fazer com ela.
 *
 * Cada passo se resolve conforme acontece; nao ha nada para marcar. */
function desenharInicio() {
  const onde = $('inicio');
  if (!onde) return;

  const vazio = (estado.chamadas || 0) === 0;

  // Uma tela, um estado. Sem isto, a tela vazia dizia "nenhuma chamada ainda"
  // em tres lugares — no placar, na tabela e aqui — e ainda deixava tres
  // titulos de secao pairando sobre blocos sem nada dentro. Enquanto nao ha o
  // que mostrar, o que aparece e o que fazer; quando ha, os passos somem.
  ['placar', 'ordem', 'credito', 'historico'].forEach(id => {
    const el = $(id);
    if (!el) return;
    el.hidden = vazio;
    // O `h2` de cada bloco e o irmao imediatamente acima dele.
    const titulo = el.previousElementSibling;
    if (titulo && titulo.tagName === 'H2') titulo.hidden = vazio;
  });

  if (!vazio) { onde.innerHTML = ''; return; }

  const provedores = (estado.provedores || []).length;
  const ferramenta = (ferramentas || []).filter(f => f.conexao)[0];

  const passos = [
    {
      feito: provedores > 0,
      titulo: T('inicio.p1.titulo'),
      texto: provedores > 0 ? T('inicio.p1.feito', { n: provedores }) : T('inicio.p1.falta')
    },
    {
      feito: !!ferramenta,
      titulo: T('inicio.p2.titulo'),
      texto: ferramenta ? T('inicio.p2.feito', { quem: ferramenta.label }) : T('inicio.p2.texto'),
      acao: ferramenta ? null : T('inicio.ir_conectar')
    },
    {
      feito: false,
      titulo: T('inicio.p3.titulo'),
      texto: T('inicio.p3.texto')
    }
  ];

  onde.innerHTML =
    '<h2>' + T('inicio.titulo') + ' <span class="risco"></span></h2>' +
    '<ol class="passos">' +
    passos.map((p, i) =>
      '<li' + (p.feito ? ' class="feito"' : '') + '>' +
      // O numero vira marca de concluido: o estado nao fica so na cor.
      '<span class="n">' + (p.feito ? '&#10003;' : '0' + (i + 1)) + '</span>' +
      '<div><strong>' + p.titulo + '</strong>' +
      '<p>' + p.texto + '</p>' +
      (p.acao ? '<button type="button" class="acao" id="ir-conectar">' + p.acao + '</button>' : '') +
      '</div></li>').join('') +
    '</ol>';

  const botao = $('ir-conectar');
  if (botao) botao.addEventListener('click', () => trocarTela('conectar'));
}

/* — Agora — */
function desenharAgora() {
  desenharInicio();
  const linhas = estado.ordem || [];
  const saude = {};
  (estado.provedores || []).forEach(p => (saude[p.nome] = p));

  // O placar responde de cabeca o que a tabela responde lendo: quem esta
  // respondendo, quanto ja passou por aqui, quantos estao de pe.
  const chamadas = estado.chamadas || 0;
  const dePe = (estado.provedores || []).filter(p => !p.cooldown).length;
  const total = (estado.provedores || []).length;
  const primeiro = linhas[0];
  const emEspera = (estado.provedores || []).filter(p => p.cooldown).length;
  $('placar').innerHTML =
    '<div><b class="verde">' + (primeiro ? primeiro.nome : '—') + '</b>' +
    '<span>primeiro da fila</span>' +
    '<small>' + (primeiro ? primeiro.motivo : 'nenhuma chamada ainda') + '</small></div>' +
    '<div><b>' + chamadas + '</b><span>chamadas</span>' +
    '<small>desde que o servidor subiu</small></div>' +
    '<div><b' + (emEspera ? ' class="ambar"' : '') + '>' + dePe + ' de ' + total + '</b>' +
    '<span>de pé</span><small>' +
    (emEspera ? emEspera + ' em espera depois de falhar' : 'ninguém em espera') + '</small></div>';

  // Uma tabela, nao duas: "ordem" e "saude" repetiam provedor e latencia lado a
  // lado, e obrigavam a cruzar as duas com o dedo para responder uma pergunta.
  $('ordem').innerHTML = linhas.length
    ? '<table><thead><tr><th></th><th>Provedor</th><th>Estado</th><th>Qualidade</th>' +
      '<th>OK / erro</th><th>Latência</th><th>Por quê</th></tr></thead><tbody>' +
      linhas.map((l, i) => {
        const s = saude[l.nome] || {};
        const par = selo(s);
        const espera = s.cooldown ? ' <span class="num" style="color:var(--ambar)">' + s.cooldown + 's</span>' : '';
        return '<tr><td class="posicao">' + (i + 1) + '</td>' +
          '<td><span class="comlogo">' + logo(l.nome) + l.nome + '</span></td>' +
          '<td><span class="selo ' + par[0] + '">' + par[1] + '</span>' + espera + '</td>' +
          '<td>' + medidor(l.qualidade_num, l.estimado) + '</td>' +
          '<td class="num">' + (s.ok || 0) + (s.err ? ' / <span style="color:var(--ruim)">' + s.err + '</span>' : ' / 0') + '</td>' +
          '<td class="num">' + l.latencia + '</td>' +
          '<td class="porque">' + l.motivo + '</td></tr>';
      }).join('') + '</tbody></table>'
    : '<p class="vazio" style="padding:22px">Nenhuma chamada ainda. A fila aparece depois do primeiro turno.</p>';
}

/* — Provedores por tier — */
const ROTULOS = { adaptive: 'Deixar ele aprender', tier: 'Meu tier manda' };

function desenharEstrategia() {
  const atual = config.estrategia;
  $('estrategia').innerHTML = Object.keys(config.estrategias).map(id =>
    '<label class="escolha" data-ativa="' + (id === atual) + '">' +
    '<input type="radio" name="estrategia" value="' + id + '"' + (id === atual ? ' checked' : '') + '>' +
    '<span><span class="titulo">' + (ROTULOS[id] || id) + '</span>' +
    '<span class="texto">' + config.estrategias[id] + '</span></span></label>').join('');
  document.querySelectorAll('input[name=estrategia]').forEach(input =>
    input.addEventListener('change', async () => {
      try {
        await salvar('config/estrategia', { valor: input.value });
        config.estrategia = input.value;
        desenharEstrategia();
        recado('recado-prov', 'Vale a partir da próxima chamada.');
      } catch (e) { recado('recado-prov', e.message); }
    }));
}

function desenharTiers() {
  const porTier = { 1: [], 2: [], 3: [] };
  // Conta nao e provedor: `ultra` e `ultra_max` batem no mesmo endpoint do
  // OpenRouter com outra chave, e listar os tres lado a lado faria parecer que
  // existem tres OpenRouters.
  (config.provedores || [])
    // Conta nao e provedor: `ultra` e `ultra_max` batem no mesmo endpoint do
    // OpenRouter com outra chave. Sao credenciais com nome, e e na tela de
    // Credenciais que elas aparecem.
    .filter(p => !p.conta_de)
    // O fallback nao e provedor: e o aviso de que nenhum respondeu.
    .filter(p => p.nome !== 'fallback')
    .forEach(p => (porTier[p.tier] || porTier[2]).push(p));

  // Só os tiers que recebem provedor. O tier 9 existia como faixa vazia que
  // não aceitava arrasto — uma caixa para não receber nada.
  $('tiers').innerHTML = Object.keys(config.tiers).filter(n => porTier[n]).map(n =>
    '<div class="faixa"' + (n === '9' ? '' : ' data-tier="' + n + '"') + '>' +
    '<div class="titulo">' + config.tiers[n] + ' <em>tier ' + n + ' · ' +
    porTier[n].length + '</em></div><div class="grade">' +
    (porTier[n].length ? porTier[n].map(p => {
      return '<div><div class="prov' + (p.na_cadeia ? '' : ' fora') + '" draggable="true" data-prov="' + p.nome + '">' +
        logo(p.nome) + '<span class="quem" title="' + p.label + '">' + p.nome + '</span>' +
        '<button type="button" class="liga" data-liga="' + p.nome + '" data-ligado="' + p.na_cadeia + '">' +
        (p.na_cadeia ? 'na cadeia' : 'fora') + '</button></div></div>';
    }).join('')
      : '<p class="vazio">vazio</p>') +
    '</div></div>').join('');

  document.querySelectorAll('.prov').forEach(el => {
    el.addEventListener('dragstart', ev => {
      el.classList.add('arrastando');
      ev.dataTransfer.setData('text/plain', el.dataset.prov);
    });
    el.addEventListener('dragend', () => el.classList.remove('arrastando'));
  });
  // A faixa do último recurso não recebe arrasto: ela existe para ser o fim.
  document.querySelectorAll('.faixa[data-tier]').forEach(faixa => {
    faixa.addEventListener('dragover', ev => { ev.preventDefault(); faixa.classList.add('alvo'); });
    faixa.addEventListener('dragleave', () => faixa.classList.remove('alvo'));
    faixa.addEventListener('drop', async ev => {
      ev.preventDefault();
      faixa.classList.remove('alvo');
      const quem = ev.dataTransfer.getData('text/plain');
      if (!quem) return;
      try {
        await salvar('config/tier', { provedor: quem, tier: Number(faixa.dataset.tier) });
        await carregarConfig();
        recado('recado-prov', quem + ' foi para o tier ' + faixa.dataset.tier + '.');
      } catch (e) { recado('recado-prov', e.message); }
    });
  });
  document.querySelectorAll('[data-liga]').forEach(b => b.addEventListener('click', async () => {
    const quem = b.dataset.liga;
    const dentro = b.dataset.ligado === 'true';
    const nova = dentro
      ? (config.cadeia || []).filter(n => n !== quem)
      : (config.cadeia || []).concat([quem]);
    try {
      await salvar('config/cadeia', { nomes: nova });
      await carregarConfig();
      recado('recado-prov', quem + (dentro ? ' saiu da cadeia.' : ' entrou na cadeia.'));
    } catch (e) { recado('recado-prov', e.message); }
  }));
}

/* — Modelos por provedor — */
let modelosDeTodos = false;

function desenharModelos() {
  // Por padrão, só quem está roteando: a lista inteira do catálogo é uma
  // parede de 44 provedores para configurar os dois que a pessoa usa.
  $('filtro-modelos').innerHTML =
    '<button class="aba" type="button" data-todos="false" aria-pressed="' + !modelosDeTodos + '">Na cadeia</button>' +
    '<button class="aba" type="button" data-todos="true" aria-pressed="' + modelosDeTodos + '">Todos do catálogo</button>';
  document.querySelectorAll('[data-todos]').forEach(b => b.addEventListener('click', () => {
    modelosDeTodos = b.dataset.todos === 'true';
    desenharModelos();
  }));

  // Provedor sem lista tambem entra: era justamente nele que faltava poder
  // acrescentar o primeiro modelo.
  const lista = (config.provedores || [])
    // O ultimo recurso nao tem modelo para escolher: ele e o aviso de que
    // nenhum provedor respondeu.
    .filter(p => p.nome !== 'fallback')
    .filter(p => modelosDeTodos || p.na_cadeia);
  $('modelos').innerHTML = lista.length ? lista.map(p => {
    const modelos = p.modelos || [];
    const linhas = modelos.length ? modelos.map((m, i) =>
      '<div class="modelo"><span class="pos">' + (i + 1) + '</span>' +
      '<span class="nome">' + m + '</span><span class="setas">' +
      '<button type="button" data-sobe="' + p.nome + '|' + i + '"' + (i === 0 ? ' disabled' : '') + '>&uarr;</button>' +
      '<button type="button" data-desce="' + p.nome + '|' + i + '"' + (i === modelos.length - 1 ? ' disabled' : '') + '>&darr;</button>' +
      '<button type="button" class="tirar" data-tira="' + p.nome + '|' + i + '" title="tirar da lista">&times;</button>' +
      '</span></div>').join('')
      : '<p class="vazio">Sem lista própria: o provedor usa o modelo padrão dele.</p>';
    return '<div class="provlinha"><div class="topo">' + logo(p.nome) +
      '<span class="quem">' + p.nome + '</span>' +
      '<span class="obs">' + (p.modelos_proprios ? 'ordem sua' : 'ordem de fábrica') +
      '<button type="button" class="descobrir" data-descobre="' + p.nome + '">ver o que ele tem</button></span></div>' +
      '<div class="modelos">' + linhas + '</div>' +
      '<div class="achados" id="achados-' + p.nome + '"></div>' +
      '<form class="somar" data-prov="' + p.nome + '">' +
      '<input placeholder="id do modelo, como ele aparece na API" autocomplete="off" spellcheck="false">' +
      '<button type="submit" class="acao">adicionar</button></form>' +
      '</div>';
  }).join('')
    : '<p class="vazio">' + (modelosDeTodos
        ? 'Nenhum provedor no catálogo.'
        : 'Nenhum provedor na cadeia. Veja o catálogo inteiro acima.') + '</p>';

  const listaDe = nome => ((config.provedores || []).filter(p => p.nome === nome)[0] || {}).modelos || [];

  const mover = (dados, passo) => {
    const partes = dados.split('|');
    const i = Number(partes[1]);
    const nova = listaDe(partes[0]).slice();
    const outro = nova[i + passo];
    nova[i + passo] = nova[i];
    nova[i] = outro;
    trocarModelos(partes[0], nova);
  };
  document.querySelectorAll('[data-sobe]').forEach(b =>
    b.addEventListener('click', () => mover(b.dataset.sobe, -1)));
  document.querySelectorAll('[data-desce]').forEach(b =>
    b.addEventListener('click', () => mover(b.dataset.desce, 1)));
  document.querySelectorAll('[data-tira]').forEach(b =>
    b.addEventListener('click', () => {
      const partes = b.dataset.tira.split('|');
      const nova = listaDe(partes[0]).slice();
      nova.splice(Number(partes[1]), 1);
      trocarModelos(partes[0], nova);
    }));

  document.querySelectorAll('form.somar').forEach(f =>
    f.addEventListener('submit', ev => {
      ev.preventDefault();
      const campo = f.querySelector('input');
      const id = campo.value.trim();
      if (!id) return;
      const atual = listaDe(f.dataset.prov);
      if (atual.indexOf(id) >= 0) { recado('recado-mod', id + ' já está na lista.'); return; }
      campo.value = '';
      trocarModelos(f.dataset.prov, atual.concat([id]));
    }));

  document.querySelectorAll('[data-descobre]').forEach(b =>
    b.addEventListener('click', async () => {
      const quem = b.dataset.descobre;
      const caixa = $('achados-' + quem);
      b.textContent = 'perguntando…';
      try {
        const r = await (await fetch('modelos/' + quem)).json();
        const achados = (r.models || r.modelos || []).map(m => m.id || m.nome || m);
        const atual = listaDe(quem);
        const novos = achados.filter(m => atual.indexOf(m) < 0);
        // Escolher, nao substituir: antes isto trocava a lista inteira pelos 12
        // primeiros que o provedor devolvesse, apagando a ordem configurada.
        caixa.innerHTML = novos.length
          ? '<p class="dica">' + quem + ' diz ter ' + achados.length +
            ' modelos. Clique para acrescentar:</p>' +
            novos.map(m => '<button type="button" class="achado" data-somar="' +
              quem + '|' + m + '">+ ' + m + '</button>').join('')
          : '<p class="dica">' + (achados.length
              ? 'Todos os ' + achados.length + ' já estão na sua lista.'
              : quem + ' não devolveu modelo nenhum.') + '</p>';
        caixa.querySelectorAll('[data-somar]').forEach(a =>
          a.addEventListener('click', () => {
            const partes = a.dataset.somar.split('|');
            trocarModelos(partes[0], listaDe(partes[0]).concat([partes[1]]));
          }));
      } catch (e) {
        caixa.innerHTML = '<p class="dica">não consegui perguntar ao ' + quem +
          ' — normalmente é chave faltando na tela de Credenciais.</p>';
      }
      b.textContent = 'ver o que ele tem';
    }));
}

async function trocarModelos(provedor, modelos) {
  try {
    await salvar('config/modelos', { provedor: provedor, modelos: modelos });
    await carregarConfig();
    recado('recado-mod', provedor + ': tenta ' + modelos[0] + ' primeiro.');
  } catch (e) { recado('recado-mod', e.message); }
}

/* — Conectar — */
function haQuanto(s) {
  if (s < 60) return 'agora';
  if (s < 3600) return 'há ' + Math.round(s / 60) + ' min';
  return 'há ' + Math.round(s / 3600) + 'h';
}

function desenharAbas(escolhida) {
  $('abas').innerHTML = ferramentas.map(f =>
    '<button class="aba" type="button" data-id="' + f.id + '" aria-pressed="' +
    (f.id === escolhida) + '">' + f.label +
    // Uma marca na própria aba: quem abre a tela vê de onde já chegou chamada
    // sem precisar clicar em cada uma para descobrir.
    (f.conexao && f.conexao.ativo ? ' <span class="ponto-ok" title="já chamou"></span>' : '') +
    '</button>').join('');

  const f = ferramentas.filter(x => x.id === escolhida)[0] || ferramentas[0];
  if (!f) return;
  $('arquivo').textContent = f.arquivo || '';
  $('config-texto').textContent = f.conteudo;
  $('como').textContent = f.como || '';

  const c = f.conexao;
  const caixa = $('conexao');
  if (caixa) {
    if (!c) {
      // Não afirma que está errado: a ferramenta pode estar configurada e
      // ociosa. O que se sabe é só que nada chegou dela ainda.
      caixa.className = 'conexao';
      caixa.innerHTML = '<b>Nenhuma chamada ainda.</b> Cole a configuração, use o ' +
        'agente uma vez e esta linha muda sozinha.';
    } else {
      const quando = haQuanto(c.ha_segundos);
      const ctx = (c.contextos || []).length
        ? ' Aprendendo em: ' + c.contextos.map(x => '<code>' + x + '</code>').join(', ') + '.'
        : '';
      caixa.className = 'conexao ' + (c.ativo ? 'viva' : 'fria');
      caixa.innerHTML = (c.ativo ? '<b>Conectado.</b> ' : '<b>Já conectou.</b> ') +
        c.chamadas + (c.chamadas === 1 ? ' chamada, ' : ' chamadas, ') +
        'a última ' + quando + '.' + ctx;
    }
  }

  document.querySelectorAll('.aba').forEach(b =>
    b.addEventListener('click', () => desenharAbas(b.dataset.id)));
}

/* — Comum — */
function recado(onde, texto) { $(onde).textContent = texto || ''; }

async function salvar(caminho, corpo) {
  const r = await fetch(caminho, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  });
  if (!r.ok) {
    const erro = await r.json().catch(() => ({}));
    throw new Error(erro.detail || 'falhou com status ' + r.status);
  }
  return r.json();
}

async function carregarCredito() {
  try {
    const d = await (await fetch('saldo')).json();
    const contas = d.contas || [];
    $('credito').innerHTML = contas.length ? contas.map(c => {
      const valor = c.saldo_usd != null ? 'US$ ' + Number(c.saldo_usd).toFixed(2)
        : c.limite != null ? 'limite ' + c.limite : (c.detalhe || '—');
      const baixo = c.saldo_usd != null && Number(c.saldo_usd) < 1;
      return '<div class="credito">' + logo(c.provedor || c.provider || '') +
        '<span>' + (c.conta || c.provedor || c.provider || '') + '</span>' +
        '<span class="valor' + (baixo ? ' baixo' : '') + '">' + valor + '</span></div>';
    }).join('') : '<p class="vazio">Nenhum provedor desta cadeia informa crédito restante.</p>';
  } catch (e) {
    $('credito').innerHTML = '<p class="vazio">Não consegui consultar o crédito.</p>';
  }
}

async function carregarHistorico() {
  try {
    const d = await (await fetch('historico?dias=30')).json();
    const resumo = d.resumo || [];
    if (!resumo.length) {
      $('historico').innerHTML =
        '<p class="vazio">Ainda não há dias registrados. Um dia vira uma barra aqui.</p>';
      return;
    }
    $('historico').innerHTML = resumo.map(r => {
      const faixa = (d.faixas || {})[r.provedor] || [];
      const barras = faixa.map(dia =>
        '<i data-s="' + dia.saude + '" title="' + dia.dia + ': ' + dia.ok + ' ok, ' +
        dia.err + ' erro' + (dia.motivo ? ' — ' + dia.motivo : '') + '"></i>').join('');
      const nota = r.dias_ruins
        ? r.dias_ruins + (r.dias_ruins === 1 ? ' dia ruim' : ' dias ruins') +
          (r.pior_motivo ? ' · ' + r.pior_motivo : '')
        : 'nenhum dia ruim';
      return '<div class="linhadia"><div class="topo">' + logo(r.provedor) +
        '<span>' + r.provedor + '</span>' +
        '<span class="up' + (r.uptime < 99 ? ' baixo' : '') + '">' + r.uptime + '%</span></div>' +
        '<div class="dias">' + barras + '</div>' +
        '<div class="legenda"><em>30 dias atrás</em><em>' + nota + '</em><em>hoje</em></div></div>';
    }).join('');
  } catch (e) {
    $('historico').innerHTML = '<p class="vazio">Não consegui ler o histórico.</p>';
  }
}

async function carregarConfig() {
  config = await (await fetch('config')).json();
  // O idioma vem junto do resto da configuracao: e uma escolha como as outras,
  // e uma chamada a menos do que pedir por uma rota so dele.
  if (config.idioma && config.idioma !== IDIOMA) {
    IDIOMA = config.idioma;
    traduzirPagina();
  }
  desenharIdioma();
  desenharEstrategia();
  desenharTiers();
  desenharModelos();
}

/* — Idioma — */
function desenharIdioma() {
  const onde = $('idioma');
  if (!onde || !config) return;
  const opcoes = config.idiomas || ['pt', 'en'];
  const nomes = { pt: 'Português', en: 'English' };
  onde.innerHTML = '<span class="dica">' + T('comum.idioma') + '</span>' +
    opcoes.map(l =>
      '<button class="aba" type="button" data-lang="' + l + '" aria-pressed="' +
      (l === IDIOMA) + '">' + (nomes[l] || l) + '</button>').join('');

  onde.querySelectorAll('[data-lang]').forEach(b =>
    b.addEventListener('click', () => trocarIdioma(b.dataset.lang)));
}

async function trocarIdioma(qual) {
  if (qual === IDIOMA) return;
  // Troca na tela antes da resposta do servidor: a escolha ja foi feita, e
  // esperar o disco para ver o proprio clique e o tipo de espera que faz uma
  // interface parecer quebrada.
  IDIOMA = qual;
  traduzirPagina();
  desenharIdioma();
  await salvar('config/idioma', { valor: qual });
  // Redesenha o que e montado pelo JS e nao carrega `data-t`.
  desenharAgora();
  desenharEstrategia();
  if (ferramentas.length) desenharAbas((document.querySelector('.aba[aria-pressed="true"]') || {}).dataset?.id);
}

async function atualizar() {
  try {
    const d = await (await fetch('painel/dados')).json();
    estado = d;
    desenharAgora();
    $('pulso').innerHTML = '<b>' + d.provedores.length + '</b> na cadeia<br>' +
      '<b>' + d.chamadas + '</b> chamadas';
    if (d.ferramentas) {
      // Redesenha sempre, e não só na primeira vez: o estado de conexão muda
      // enquanto a tela está aberta, e é justamente isso que se quer ver —
      // colar a configuração, usar o agente, e a linha mudar sozinha.
      const escolhida = (document.querySelector('.aba[aria-pressed="true"]') || {}).dataset;
      ferramentas = d.ferramentas;
      desenharAbas((escolhida && escolhida.id) || (ferramentas[0] && ferramentas[0].id));
    }
  } catch (e) { $('pulso').textContent = 'servidor fora do ar'; }
}

let contasDeTodos = false;
let contas = { contas: [], tiers: {}, alvos: {} };

async function carregarCredenciais() {
  try {
    contas = await (await fetch('contas')).json();
    const d = await (await fetch('credenciais')).json();
    $('onde-cofre').textContent = d.cofre ? 'Cofre desta máquina: ' + d.cofre : '';
  } catch (e) { $('credenciais').textContent = 'não consegui ler as contas'; return; }

  desenharReservados();
  desenharContas();
  desenharFormDeConta();
  ligarImportacao();
}

function desenharReservados() {
  // Qual conta serve cada tier de selecao. E o que separa "gaste a gratuita"
  // de "pode gastar meu credito".
  const alvos = contas.alvos || {};
  const nomes = Object.keys(alvos);
  if (!nomes.length) { $('reservados').innerHTML = ''; return; }
  const opcoes = (contas.contas || []).filter(c => c.configurada);
  $('reservados').innerHTML = '<h2>Reservado para as tarefas pesadas</h2>' + nomes.map(t =>
    '<div class="reservado"><strong>' + alvos[t] + '</strong>' +
    '<p>Quando o agente pedir este modo, o RobinBandit usa esta conta em vez de decidir sozinho.</p>' +
    '<select data-tier="' + t + '">' +
    '<option value="">decidir sozinho</option>' +
    opcoes.map(c => '<option value="' + c.id + '"' +
      ((contas.tiers || {})[t] === c.id ? ' selected' : '') + '>' +
      c.label + (c.paga ? ' · paga' : '') + '</option>').join('') +
    '</select></div>').join('');

  document.querySelectorAll('[data-tier]').forEach(sel =>
    sel.addEventListener('change', async () => {
      try {
        const r = await fetch('contas/tier', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: sel.dataset.tier, conta: sel.value }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || 'não deu');
        recado('recado-cred', 'Pronto. Vale já na próxima chamada.');
      } catch (e) { recado('recado-cred', e.message); }
    }));
}

function desenharContas() {
  $('filtro-cred').innerHTML =
    '<button class="aba" type="button" data-cred="false" aria-pressed="' + !contasDeTodos + '">Configuradas</button>' +
    '<button class="aba" type="button" data-cred="true" aria-pressed="' + contasDeTodos + '">Todas</button>';
  document.querySelectorAll('[data-cred]').forEach(b => b.addEventListener('click', () => {
    contasDeTodos = b.dataset.cred === 'true';
    desenharContas();
  }));

  const lista = (contas.contas || [])
    // O ultimo recurso nao tem conta: ele e o aviso de que ninguem respondeu.
    .filter(c => c.provider !== 'fallback')
    .filter(c => contasDeTodos || c.configurada);
  if (!lista.length) {
    $('credenciais').innerHTML = '<p class="vazio">' + (contasDeTodos
      ? 'Nenhuma conta no catálogo.'
      : 'Nenhuma conta configurada ainda. Veja todas acima e cole uma chave.') + '</p>';
    return;
  }

  const porProvedor = {};
  lista.forEach(c => (porProvedor[c.provider] = porProvedor[c.provider] || []).push(c));

  $('credenciais').innerHTML = Object.keys(porProvedor).sort().map(prov =>
    '<div class="grupo-cred"><h2>' + logo(prov) + prov + '</h2>' +
    porProvedor[prov].map(c => {
      // Quem autentica pelo CLI oficial nao tem chave para colar: pedir uma
      // mandava a pessoa procurar algo que nao existe nesse fluxo.
      if (c.por_cli) {
        const qual = c.auth_type === 'codex_cli' ? 'Codex CLI' : 'Claude Code';
        const comando = c.auth_type === 'codex_cli' ? 'codex login' : 'claude';
        return '<div class="cred"><div class="topo">' +
          '<span class="var">' + c.label + '</span>' +
          '<span class="estado' + (c.configurada ? ' tem' : '') + '">' +
          (c.configurada ? 'autenticado' : 'não conectado') + '</span></div>' +
          '<p class="cli">Quem autentica é o <b>' + qual + '</b>, com a assinatura que você já usa. ' +
          'O RobinBandit não lê nem renova credencial — só chama o executável.' +
          // O detalhe so entra quando acrescenta (a versao do CLI, o motivo
          // de nao estar logado). "autenticado" depois de "autenticado" e eco.
          (c.detalhe && c.detalhe !== 'autenticado' ? ' <em>' + c.detalhe + '</em>' : '') +
          (c.configurada ? '' : ' Rode <code>' + comando + '</code> no terminal e recarregue.') +
          '</p></div>';
      }
      // A marca de paga e da CHAVE. Em cima, na variavel, ela dizia que TODAS as
      // chaves daquela conta eram pagas — e uma conta pode ter uma gratuita e
      // uma paga lado a lado.
      const chaves = (c.chaves || []).map(k =>
        '<span class="chave' + (k.paga ? ' e-paga' : '') + '">' +
        '<b' + (k.nome ? '' : ' class="anonima"') + '>' + (k.nome || 'sem nome') + '</b>' +
        '<span class="dica">' + k.dica + '</span>' +
        '<button type="button" class="marca-paga' + (k.paga ? '' : ' off') + '" data-paga="' +
        c.key_env + '" data-i="' + k.i + '" data-vale="' + (k.paga ? '1' : '0') +
        '" title="' + (k.paga ? 'crédito pago — clique para desmarcar' : 'marcar como crédito pago') +
        '">paga</button>' +
        '<span class="acoes">' +
        '<button type="button" data-renomear="' + c.key_env + '" data-i="' + k.i +
        '" data-nome="' + (k.nome || '') + '" title="dar um nome a esta chave">&#9998;</button>' +
        '<button type="button" class="apagar" data-apagar="' + c.key_env + '" data-i="' + k.i +
        '" title="remover esta chave">&times;</button></span>' +
        '</span>').join('');
      return '<div class="cred">' +
        '<div class="topo">' +
        '<span class="var">' + c.key_env + '</span>' +
        (c.label && c.label !== c.provider ? '<span class="conta-nome">' + c.label + '</span>' : '') +
        '<span class="estado' + (c.configurada ? ' tem' : '') + '">' +
        (c.configurada ? c.origem : 'sem chave') + '</span>' +
        '</div>' +
        (chaves ? '<div class="chaves">' + chaves + '</div>' : '') +
        '<form data-var="' + c.key_env + '">' +
        '<input class="valor" type="password" placeholder="' +
        (c.configurada ? 'adicionar outra chave' : 'colar a chave') +
        '" autocomplete="off" spellcheck="false">' +
        '<input class="apelido" placeholder="apelido, ex.: conta pessoal" autocomplete="off">' +
        '<label class="paga"><input type="checkbox" class="e-paga"> crédito pago</label>' +
        '<button type="submit" class="acao">guardar no cofre</button>' +
        '</form></div>';
    }).join('') + '</div>').join('');

  document.querySelectorAll('#credenciais form').forEach(f =>
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      const campo = f.querySelector('input.valor');
      const apelido = f.querySelector('input.apelido');
      const paga = f.querySelector('input.e-paga');
      const valor = campo.value.trim();
      if (!valor) return;
      try {
        const r = await fetch('credenciais', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            variavel: f.dataset.var, valor: valor, adicionar: true,
            rotulo: apelido.value.trim(), paga: paga.checked,
          }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || 'não deu');
        // O valor nao volta nem para o campo: some daqui na hora.
        campo.value = '';
        apelido.value = '';
        paga.checked = false;
        recado('recado-cred', f.dataset.var + ' guardada no cofre.');
        carregarCredenciais();
      } catch (e) { recado('recado-cred', e.message); }
    }));

  document.querySelectorAll('#credenciais [data-paga]').forEach(b =>
    b.addEventListener('click', async () => {
      try {
        await fetch('credenciais/' + b.dataset.paga + '/' + b.dataset.i, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ paga: b.dataset.vale !== '1' }),
        });
        carregarCredenciais();
      } catch (e) { recado('recado-cred', e.message); }
    }));

  document.querySelectorAll('#credenciais [data-renomear]').forEach(b =>
    b.addEventListener('click', async () => {
      const atual = b.dataset.nome || '';
      const nome = prompt('Nome desta chave (para você saber qual é qual):', atual);
      if (nome === null) return;
      try {
        await fetch('credenciais/' + b.dataset.renomear + '/' + b.dataset.i, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rotulo: nome }),
        });
        carregarCredenciais();
      } catch (e) { recado('recado-cred', e.message); }
    }));

  document.querySelectorAll('#credenciais [data-apagar]').forEach(b =>
    b.addEventListener('click', async () => {
      try {
        await fetch('credenciais/' + b.dataset.apagar + '/' + b.dataset.i, { method: 'DELETE' });
        recado('recado-cred', 'Removida do cofre. O ambiente não foi tocado.');
        carregarCredenciais();
      } catch (e) { recado('recado-cred', e.message); }
    }));
}

function milhar(n) {
  // "48,0 mi" le-se; "48000000" faz contar zero.
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.', ',') + ' bi';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', ',') + ' mi';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace('.', ',') + ' mil';
  return String(n);
}

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const SEMANA = ['', 'seg', '', 'qua', '', 'sex', ''];

function calendarioDe(dias) {
  // Comeca no domingo da primeira semana, senao as linhas nao sao dias da
  // semana — e um calendario cujas linhas nao sao dias nao e um calendario.
  const primeiro = new Date(dias[0].dia + 'T00:00:00Z');
  const vazios = primeiro.getUTCDay();
  const pico = Math.max(1, ...dias.map(x => x.total));

  const celulas = [];
  for (let i = 0; i < vazios; i++) celulas.push('<i class="fora"></i>');
  dias.forEach(x => {
    const n = x.total === 0 ? 0 : Math.min(4, Math.ceil(x.total / pico * 4));
    const quanto = x.total
      ? milhar(x.total) + ' tokens em ' + x.chamadas + ' chamada' + (x.chamadas === 1 ? '' : 's')
      : 'sem uso';
    celulas.push('<i data-n="' + n + '" title="' + x.dia + ' — ' + quanto + '"></i>');
  });

  // Um rotulo por mes, largo o bastante para cobrir as semanas dele.
  const colunas = Math.ceil(celulas.length / 7);
  const porColuna = [];
  for (let c = 0; c < colunas; c++) {
    const idx = c * 7 - vazios;
    const dia = dias[Math.max(0, Math.min(dias.length - 1, idx))];
    porColuna.push(new Date(dia.dia + 'T00:00:00Z').getUTCMonth());
  }
  const rotulos = [];
  let atual = -1, largura = 0;
  porColuna.forEach((mes, i) => {
    if (mes !== atual) {
      if (largura) rotulos.push({ mes: atual, largura: largura });
      atual = mes; largura = 1;
    } else { largura++; }
    if (i === porColuna.length - 1) rotulos.push({ mes: atual, largura: largura });
  });

  return '<div class="quadro">' +
    '<div class="meses" style="grid-template-columns:' +
    rotulos.map(r => 'calc(' + r.largura + ' * 15px)').join(' ') + '">' +
    // Mes de uma semana so nao cabe o nome, e o rotulo cortado polui mais do
    // que informa.
    rotulos.map(r => '<span>' + (r.largura > 2 ? MESES[r.mes] : '') + '</span>').join('') +
    '</div>' +
    '<div class="semana">' + SEMANA.map(d => '<span>' + d + '</span>').join('') + '</div>' +
    '<div class="malha">' + celulas.join('') + '</div>' +
    '</div>' +
    '<div class="legenda"><b>menos</b>' +
    [0, 1, 2, 3, 4].map(n => '<i data-n="' + n + '"></i>').join('') +
    '<b style="margin-left:4px">mais</b>' +
    '<span class="fim">cada quadrado é um dia; o mais escuro é o dia em que você mais gastou</span>' +
    '</div>';
}

async function carregarUso() {
  let d;
  try { d = await (await fetch('uso?dias=365')).json(); }
  catch (e) { $('uso-calendario').textContent = 'não consegui ler o uso'; return; }

  const mes = d.mes || {};
  const tudo = d.total || {};
  const dias = d.calendario || [];
  const gastou = (tudo.total || 0) > 0;

  // Cinco zeros sobre uma grade vazia parecem defeito. Sem dado, o que vale
  // dizer e por que ainda nao ha dado.
  // O gasto e SEU, somado. Uma lista de 14 provedores no topo respondia
  // "quanto cada um gastou" quando a pergunta era "quanto eu gastei".
  $('uso-numeros').innerHTML = gastou
    ? '<div><b class="verde">' + milhar(mes.total || 0) + '</b><span>tokens em 30 dias</span>' +
      '<small>' + milhar(mes.entrada || 0) + ' de entrada · ' + milhar(mes.saida || 0) + ' de saída</small></div>' +
      '<div><b>' + (mes.chamadas || 0) + '</b><span>chamadas</span>' +
      '<small>em ' + (mes.provedores || 0) + ' provedor' + (mes.provedores === 1 ? '' : 'es') + '</small></div>' +
      '<div><b>' + milhar(tudo.total || 0) + '</b><span>no ano</span>' +
      (mes.cacheado ? '<small>' + milhar(mes.cacheado) + ' vieram do cache</small>' : '<small>desde o primeiro turno</small>') +
      '</div>'
    : '';

  $('uso-calendario').innerHTML = gastou
    ? calendarioDe(dias)
    : '<div class="sem-uso"><b>Nenhum turno medido ainda</b><span>' +
      'A contagem começa na primeira resposta que passar por aqui. Aponte sua ' +
      'ferramenta para este endereço na tela Conectar — só entra no gráfico quem ' +
      'informa o consumo junto da resposta.</span></div>';

  const linhas = d.por_provedor || [];
  const maior = Math.max(1, ...linhas.map(x => x.total));
  $('uso-detalhe').hidden = !linhas.length;
  $('uso-provedores').innerHTML = linhas.map(x =>
    '<div class="gasto">' + logo(x.provedor) +
    '<span class="quem">' + x.provedor + '</span>' +
    '<span class="barra"><span style="width:' + Math.round(x.total / maior * 100) + '%"></span></span>' +
    '<span class="n">' + milhar(x.total) + '</span></div>').join('');
}

async function carregarJanelas() {
  let d;
  try { d = await (await fetch('janelas')).json(); }
  catch (e) { $('janelas').textContent = 'não consegui ler as janelas'; return; }

  const linhas = d.janelas || [];
  $('janelas').innerHTML = linhas.length ? linhas.map(j => {
    if (!j.aberta) {
      return '<div class="janela parada"><div class="topo">' + logo(j.provedor) +
        '<span class="quem">' + j.provedor + '</span>' +
        '<span class="quanto"><small>bloco fechado</small></span></div>' +
        '<p class="conta">Nenhuma chamada na janela atual. A próxima abre um bloco de ' +
        j.horas + 'h.</p></div>';
    }
    const pct = Math.round(j.fracao * 100);
    // Passando de 80% do bloco, o que importa e que ele esta perto de virar.
    const perto = j.fracao >= 0.8 ? ' perto' : '';
    return '<div class="janela"><div class="topo">' + logo(j.provedor) +
      '<span class="quem">' + j.provedor + '</span>' +
      '<span class="quanto">' + j.vira_em + ' <small>para virar</small></span></div>' +
      '<div class="trilho"><div class="cheio' + perto + '" style="width:' + pct + '%"></div></div>' +
      '<p class="conta">' + j.chamadas + ' chamada' + (j.chamadas === 1 ? '' : 's') +
      ' neste bloco de ' + j.horas + 'h' +
      (j.bloqueios ? ' · <b>parou por limite ' + j.bloqueios + 'x</b>' : '') +
      (j.erros ? ' · ' + j.erros + ' erro' + (j.erros === 1 ? '' : 's') : '') +
      '</p></div>';
  }).join('')
    : '<p class="vazio">Nenhum provedor de assinatura na cadeia. Janela é coisa de ' +
      'assinatura: quem cobra por token tem limite por minuto, e disso o roteador ' +
      'já cuida sozinho.</p>';

  const p = d.ping || {};
  $('ping').innerHTML =
    '<div class="topo"><h2>Perguntar se a cota já voltou</h2>' +
    '<button type="button" class="acao liga-ping" id="btn-ping">' +
    (p.ativo ? 'desligar' : 'ligar') + '</button></div>' +
    '<p>O cooldown vence por tempo, não por evidência: se a cota voltou antes, o ' +
    'roteador continua ignorando o provedor; se não voltou, quem descobre é o seu ' +
    'próximo turno. O ping é uma chamada mínima, fora de um turno, só para saber — ' +
    'custa cota para medir cota, e por isso vem desligado.</p>' +
    '<div class="campos">' +
    '<label>a cada <input type="number" id="ping-intervalo" min="60" step="30" value="' +
    Math.round(p.intervalo_s || 300) + '"> segundos</label>' +
    '<label><input type="checkbox" id="ping-cooldown"' + (p.so_em_cooldown ? ' checked' : '') +
    '> só quem está fora</label>' +
    '</div>';

  $('btn-ping').addEventListener('click', () => salvarPing({ ativo: !p.ativo }));
  $('ping-intervalo').addEventListener('change', ev =>
    salvarPing({ intervalo_s: Number(ev.target.value) }));
  $('ping-cooldown').addEventListener('change', ev =>
    salvarPing({ so_em_cooldown: ev.target.checked }));
}

async function salvarPing(mudanca) {
  try {
    const r = await fetch('janelas/ping', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mudanca),
    });
    if (!r.ok) throw new Error('não deu');
    recado('recado-janela', 'Pronto.');
    carregarJanelas();
  } catch (e) { recado('recado-janela', e.message); }
}

function ligarImportacao() {
  const b = $('btn-importar');
  if (!b || b.dataset.pronto) return;
  b.dataset.pronto = '1';
  b.addEventListener('click', async () => {
    b.disabled = true;
    b.textContent = 'trazendo…';
    try {
      const d = await (await fetch('credenciais/importar', { method: 'POST' })).json();
      recado('recado-cred', d.trazidas.length
        ? d.trazidas.length + ' no cofre: ' + d.trazidas.join(', ')
        : 'Nada novo: o cofre já tem tudo que o ambiente tinha.');
      carregarCredenciais();
    } catch (e) { recado('recado-cred', 'não consegui trazer'); }
    b.disabled = false;
    b.textContent = 'trazer para o cofre';
  });
}

function desenharFormDeConta() {
  const provs = (config.provedores || [])
    .filter(p => p.nome !== 'fallback' && !p.conta_de)
    .map(p => p.nome).sort();
  $('conta-prov').innerHTML = provs.map(n => '<option value="' + n + '">' + n + '</option>').join('');

  const form = $('form-conta');
  if (form.dataset.pronto) return;
  form.dataset.pronto = '1';
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const corpo = {
      id: $('conta-id').value.trim(),
      provedor: $('conta-prov').value,
      variavel: $('conta-var').value.trim().toUpperCase(),
      label: $('conta-id').value.trim(),
      paga: $('conta-paga').checked,
    };
    if (!corpo.id || !corpo.variavel) { recado('recado-cred', 'Falta o apelido ou o nome da variável.'); return; }
    try {
      const r = await fetch('contas', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'não deu');
      $('conta-id').value = ''; $('conta-var').value = ''; $('conta-paga').checked = false;
      recado('recado-cred', 'Conta criada. Agora cole a chave dela abaixo.');
      contasDeTodos = true;
      carregarCredenciais();
    } catch (e) { recado('recado-cred', e.message); }
  });
}

const TELAS = ['agora', 'provedores', 'modelos', 'credenciais', 'janelas', 'uso', 'conectar'];

/* Extraida do listener para o botao dos primeiros passos poder chamar: dois
 * lugares trocando de tela com a mesma logica escrita duas vezes sairiam do
 * lugar no primeiro ajuste. */
function trocarTela(qual) {
  document.querySelectorAll('nav button[data-tela]').forEach(b => {
    // Tem que ser "page", não string vazia: o realce da aba ativa vem de
    // `nav button[aria-current="page"]` no CSS, e `toggleAttribute` grava "".
    if (b.dataset.tela === qual) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  TELAS.forEach(t => $('tela-' + t).classList.toggle('oculto', t !== qual));
}

document.querySelectorAll('nav button[data-tela]').forEach(b =>
  b.addEventListener('click', () => trocarTela(b.dataset.tela)));

carregarConfig().catch(() => recado('recado-prov', 'não consegui ler a configuração'));
carregarCredito();
carregarCredenciais();
carregarJanelas();
carregarUso();
carregarHistorico();
atualizar();
setInterval(atualizar, 4000);
