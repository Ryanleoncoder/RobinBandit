const $ = id => document.getElementById(id);
let config = null;
let ferramentas = [];
let estado = { provedores: [], ordem: [], atividade: [] };
let periodoUso = 30;

const L = (pt, en) => IDIOMA === 'en' ? en : pt;

function logo(nome) {
  const sigla = (nome || '?').slice(0, 2).toUpperCase();
  return '<img class="logo" src="logos/' + nome + '.svg" alt="" ' +
    'onerror="this.outerHTML=\'<span class=&quot;logo falta&quot;>' + sigla + '</span>\'">';
}

function selo(p) {
  // Derivado dos contadores persistidos, não do status inicial do processo.
  if (p.cooldown) return ['mau', L('em espera', 'waiting')];
  const ok = p.ok || 0, err = p.err || 0, total = ok + err;
  if (!total) return ['', L('sem uso', 'idle')];
  const taxa = ok / total;
  if (taxa >= 0.95) return ['bom', L('saudável', 'healthy')];
  if (taxa >= 0.7) return ['atencao', L('instável', 'shaky')];
  return ['mau', L('falhando', 'failing')];
}

function medidor(valor, estimado) {
  // Sem histórico, o número é o prior do catálogo.
  const n = Number(valor) || 0;
  const faixa = n >= 0.75 ? '' : n >= 0.5 ? ' medio' : ' baixo';
  return '<span class="medidor"><span class="trilho">' +
    '<span class="cheio' + faixa + '" style="width:' + Math.round(n * 100) + '%"></span></span>' +
    '<span class="valor' + (estimado ? ' palpite' : '') + '" title="' +
    (estimado ? L('palpite de fábrica: este provedor ainda não foi usado', 'factory guess: this provider has not been used yet') : L('medido aqui', 'measured here')) +
    '">' + (n ? n.toFixed(2) : '—') + '</span>' +
    (estimado && n ? '<span class="palpite-nota">' + L('palpite', 'guess') + '</span>' : '') + '</span>';
}

/* — Primeiros passos — */
function desenharInicio() {
  const onde = $('inicio');
  if (!onde) return;

  const vazio = (estado.chamadas || 0) === 0 && !(estado.atividade || []).length;

  // Antes da primeira chamada, mostra só o onboarding.
  ['placar', 'fluxo', 'atividade', 'ordem', 'credito', 'historico'].forEach(id => {
    const el = $(id);
    if (!el) return;
    el.hidden = vazio;
    // O `h2` de cada bloco é o irmão imediatamente acima dele.
    const titulo = el.previousElementSibling;
    if (titulo && titulo.tagName === 'H2') titulo.hidden = vazio;
  });

  if (!vazio) { onde.innerHTML = ''; return; }

  const listaProvedores = (estado.provedores || []).map(p => {
    const conhecido = ((config && config.provedores) || []).find(c => c.nome === p.nome);
    return conhecido ? conhecido.label : p.nome;
  });
  const tituloAtividade = $('titulo-atividade');
  if (tituloAtividade) tituloAtividade.hidden = vazio;
  const notaAtividade = $('nota-atividade');
  if (notaAtividade) notaAtividade.hidden = vazio;
  const provedores = listaProvedores.length;
  const ferramenta = (ferramentas || []).filter(f => f.conexao)[0];

  const passos = [
    {
      feito: provedores > 0,
      titulo: T('inicio.p1.titulo'),
      texto: provedores > 0
        ? T('inicio.p1.feito', { quem: listaProvedores.join(' + ') })
        : T('inicio.p1.falta')
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
      // Marca conclusão também por texto, não só por cor.
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

  // Resumo rápido do estado que a tabela detalha abaixo.
  const chamadas = estado.chamadas || 0;
  const dePe = (estado.provedores || []).filter(p => !p.cooldown).length;
  const total = (estado.provedores || []).length;
  const primeiro = linhas[0];
  const emEspera = (estado.provedores || []).filter(p => p.cooldown).length;
  const atividade = estado.atividade || [];
  const abertas = atividade.filter(a => a.status === 'em_andamento');
  const ultima = atividade[0];
  $('placar').innerHTML =
    '<div><b class="verde">' + (primeiro ? primeiro.nome : '—') + '</b>' +
    '<span>' + L('primeiro da fila', 'first in queue') + '</span>' +
    '<small>' + T('prov.modo.' + (estado.estrategia || 'adaptive')) +
    (primeiro && primeiro.motivo ? ': ' + primeiro.motivo : '') + '</small></div>' +
    '<div><b>' + chamadas + '</b><span>' + L('chamadas', 'calls') + '</span>' +
    '<small>' + L('desde que o servidor subiu', 'since the server started') + '</small></div>' +
    '<div><b' + (emEspera ? ' class="ambar"' : '') + '>' + dePe + ' de ' + total + '</b>' +
    '<span>' + L('de pé', 'available') + '</span><small>' +
    (emEspera ? emEspera + L(' em espera depois de falhar', ' waiting after failure') : L('ninguém em espera', 'nobody waiting')) + '</small></div>' +
    '<div><b' + (abertas.length ? ' class="ambar"' : '') + '>' + abertas.length + '</b>' +
    '<span>' + L('em andamento', 'running') + '</span><small>' + (ultima
      ? (ultima.status === 'em_andamento' ? L('roteando agora', 'routing now') : L('atividade ', 'activity ') + haQuanto(ultima.ha_segundos))
      : L('nenhuma desde que subiu', 'none since startup')) + '</small></div>';

  desenharAtividade(atividade);

  // Uma tabela combina ordem e saúde.
  $('ordem').innerHTML = linhas.length
    ? '<table><thead><tr><th></th><th>' + L('Provedor', 'Provider') + '</th><th>' + L('Estado', 'State') + '</th><th>' + L('Qualidade', 'Quality') + '</th>' +
      '<th>OK / ' + L('erro', 'error') + '</th><th>' + L('Latência', 'Latency') + '</th><th>' + L('Cota', 'Quota') + '</th><th>' + L('Por quê', 'Why') + '</th></tr></thead><tbody>' +
      linhas.map((l, i) => {
        const s = saude[l.nome] || {};
        const par = selo(s);
        const espera = s.cooldown ? ' <span class="num" style="color:var(--ambar)">' + s.cooldown + 's</span>' : '';
        const recente = s.em_andamento
          ? '<span class="agora">' + L('respondendo agora', 'answering now') + '</span>'
          : s.ultimo_modelo
            ? s.ultimo_modelo + (s.ha_segundos != null ? ' · ' + haQuanto(s.ha_segundos) : '')
            : l.motivo;
        const cota = s.rpm_restante != null
          ? s.rpm_restante + ' rpm'
          : s.rpd_restante != null ? s.rpd_restante + ' ' + L('dia', 'day') : '—';
        return '<tr><td class="posicao">' + (i + 1) + '</td>' +
          '<td><span class="comlogo">' + logo(l.nome) + l.nome + '</span></td>' +
          '<td><span class="selo ' + par[0] + '">' + par[1] + '</span>' + espera + '</td>' +
          '<td>' + medidor(l.qualidade_num, l.estimado) + '</td>' +
          '<td class="num">' + (s.ok || 0) + (s.err ? ' / <span style="color:var(--ruim)">' + s.err + '</span>' : ' / 0') + '</td>' +
          '<td class="num">' + l.latencia + '</td>' +
          '<td class="num cota">' + cota + '</td>' +
          '<td class="porque">' + recente + '</td></tr>';
      }).join('') + '</tbody></table>'
    : '<p class="vazio" style="padding:22px">' + L('Nenhuma chamada ainda. A fila aparece depois do primeiro turno.', 'No calls yet. The queue appears after the first turn.') + '</p>';
}

/* — Provedores por tier — */
let provedoresDeTodos = false;

function desenharEstrategia() {
  const atual = config.estrategia;
  $('estrategia').innerHTML = Object.keys(config.estrategias).map(id =>
    '<label class="escolha" data-ativa="' + (id === atual) + '">' +
    '<input type="radio" name="estrategia" value="' + id + '"' + (id === atual ? ' checked' : '') + '>' +
    '<span><span class="titulo">' + T('prov.modo.' + id) + '</span>' +
    '<span class="texto">' + config.estrategias[id] + '</span></span></label>').join('');
  document.querySelectorAll('input[name=estrategia]').forEach(input =>
    input.addEventListener('change', async () => {
      try {
        await salvar('config/estrategia', { valor: input.value });
        config.estrategia = input.value;
        provedoresDeTodos = false;
        desenharEstrategia();
        desenharOrdemCadeia();
        desenharTiers();
        recado('recado-prov', L('Vale a partir da próxima chamada.', 'Applies from the next call.'));
      } catch (e) { recado('recado-prov', e.message); }
    }));
}

function usoCurto(uso) {
  if (!uso) return '';
  const partes = [];
  if (uso.total) partes.push(milhar(uso.total) + ' tokens');
  if (uso.custo_usd != null) partes.push(dolar(uso.custo_usd));
  return partes.join(' · ');
}

function nomeModoChamada(modo) {
  if (modo === 'hybrid') return L('Reforçado', 'Reinforced');
  if (modo === 'strict') return L('Dedicado', 'Dedicated');
  return 'Normal';
}

function desenharAtividade(itens) {
  const onde = $('atividade');
  const fluxo = $('fluxo');
  const atual = itens.find(a => a.status === 'em_andamento') || itens[0];
  if (!atual) {
    fluxo.innerHTML = '<div class="fluxo-vazio">' + L('A fila está pronta. A próxima tentativa aparece aqui enquanto acontece.', 'The queue is ready. The next attempt appears here while it runs.') + '</div>';
    onde.innerHTML = '<p class="vazio">' + L('Nenhuma tentativa desde que o servidor subiu.', 'No attempt since the server started.') + '</p>';
    return;
  }

  const viva = atual.status === 'em_andamento';
  const contexto = atual.contexto ? '<code>' + atual.contexto + '</code>' : L('contexto padrão', 'default context');
  const modo = nomeModoChamada(atual.modo);
  fluxo.innerHTML = '<div class="fluxo-cabeca"><span class="ao-vivo' + (viva ? ' ligado' : '') + '">' +
    (viva ? L('ao vivo', 'live') : L('mais recente', 'latest')) + '</span><span>' + modo + ' · ' + contexto + '</span></div>' +
    '<div class="rota-viva"><b>RobinBandit</b><span class="fio' + (viva ? ' correndo' : '') + '"><i></i></span>' +
    '<span class="destino">' + logo(atual.provedor) + '<b>' + atual.provedor + '</b></span></div>' +
    '<p>' + (viva ? L('Aguardando resposta', 'Waiting for response') : atual.status === 'sucesso' ? L('Resposta concluída', 'Response completed') : L('Tentativa encerrada', 'Attempt closed')) +
    (atual.modelo ? ' ' + L('com', 'with') + ' <code>' + atual.modelo + '</code>' : '') + '.</p>';

  onde.innerHTML = itens.slice(0, 4).map(a => {
    const classe = a.status === 'sucesso' ? 'ok' : a.status === 'falha' ? 'erro' : 'rodando';
    const duracao = a.duracao_ms != null ? a.duracao_ms + ' ms' : L('agora', 'now');
    const detalhe = [a.modelo || a.contexto, usoCurto(a.uso), a.motivo].filter(Boolean).join(' · ');
    return '<div class="atividade-linha"><span class="atividade-estado ' + classe + '"></span>' +
      logo(a.provedor) + '<span class="atividade-quem"><b>' + a.provedor + '</b><small>' +
      (detalhe || L('tentativa em andamento', 'attempt running')) + '</small></span>' +
      '<span class="atividade-tempo"><b>' + duracao + '</b><small>' + haQuanto(a.ha_segundos) + '</small></span></div>';
  }).join('');
}

function desenharOrdemCadeia() {
  const onde = $('ordem-cadeia');
  const mostra = config.estrategia === 'fixed' || config.estrategia === 'round_robin';
  onde.hidden = !mostra;
  if (!mostra) { onde.innerHTML = ''; return; }
  const catalogo = new Map((config.provedores || []).map(p => [p.nome, p]));
  const nomes = (config.cadeia || []).filter(n => n !== 'fallback' && catalogo.has(n));
  onde.innerHTML = '<h2>' + T('prov.ordem') + ' <span class="risco"></span></h2>' +
    '<p class="dica">' + T('prov.ordem.' + config.estrategia) + '</p>' +
    '<ol class="lista-cadeia">' + nomes.map((nome, i) => {
      const p = catalogo.get(nome);
      return '<li>' + logo(nome) + '<span>' + (p.label || nome) + '</span>' +
        '<code>' + nome + '</code><span class="mover">' +
        '<button type="button" data-move="-1" data-indice="' + i + '" aria-label="' + L('Subir ', 'Move up ') + nome + '"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" data-move="1" data-indice="' + i + '" aria-label="' + L('Descer ', 'Move down ') + nome + '"' + (i === nomes.length - 1 ? ' disabled' : '') + '>↓</button>' +
        '</span></li>';
    }).join('') + '</ol>';
  onde.querySelectorAll('[data-move]').forEach(botao => botao.addEventListener('click', async () => {
    const de = Number(botao.dataset.indice);
    const para = de + Number(botao.dataset.move);
    const nova = nomes.slice();
    [nova[de], nova[para]] = [nova[para], nova[de]];
    try {
      await salvar('config/cadeia', { nomes: nova });
      config.cadeia = nova;
      desenharOrdemCadeia();
      recado('recado-prov', L('Nova ordem aplicada.', 'New order applied.'));
    } catch (e) { recado('recado-prov', e.message); }
  }));
}

function desenharTiers() {
  const porTier = { 1: [], 2: [], 3: [] };
  const modoDeOrdem = config.estrategia === 'fixed' || config.estrategia === 'round_robin';
  $('filtro-provedores').innerHTML = modoDeOrdem
    ? '<button class="aba" type="button" data-provedores="' + !provedoresDeTodos + '" aria-pressed="' + provedoresDeTodos + '">' +
      (provedoresDeTodos ? T('prov.voltar_ordem') : T('prov.catalogo')) + '</button>'
    : '<button class="aba" type="button" data-provedores="false" aria-pressed="' + !provedoresDeTodos + '">' +
      T('prov.na_cadeia') + '</button>' +
      '<button class="aba" type="button" data-provedores="true" aria-pressed="' + provedoresDeTodos + '">' +
      T('prov.catalogo') + '</button>';
  document.querySelectorAll('[data-provedores]').forEach(b => b.addEventListener('click', () => {
    provedoresDeTodos = b.dataset.provedores === 'true';
    desenharTiers();
  }));

  // Conta nomeada não entra como provedor independente.
  (config.provedores || [])
    // Contas derivadas aparecem em Credenciais, não como provedores.
    .filter(p => !p.conta_de)
    // O fallback é aviso, não provedor configurável.
    .filter(p => p.nome !== 'fallback')
    // Catálogo é possibilidade; a tela abre com o que está em uso.
    .filter(p => provedoresDeTodos || p.na_cadeia)
    .forEach(p => (porTier[p.tier] || porTier[2]).push(p));

  // Só tiers que recebem provedor.
  const tiersVisiveis = Object.keys(config.tiers).filter(n => porTier[n] && porTier[n].length);
  $('tiers').hidden = modoDeOrdem && !provedoresDeTodos;
  $('nota-fallback').hidden = modoDeOrdem && !provedoresDeTodos;
  $('tiers').innerHTML = tiersVisiveis.length ? tiersVisiveis.map(n =>
    '<div class="faixa"' + (n === '9' ? '' : ' data-tier="' + n + '"') + '>' +
    '<div class="titulo">' + config.tiers[n] + ' <em>tier ' + n + ' · ' +
    porTier[n].length + '</em></div><div class="grade">' +
    (porTier[n].length ? porTier[n].map(p => {
      return '<div><div class="prov' + (p.na_cadeia ? '' : ' fora') + '" draggable="true" data-prov="' + p.nome + '">' +
        logo(p.nome) + '<span class="quem" title="' + p.label + '">' + p.nome + '</span>' +
        '<button type="button" class="liga" data-liga="' + p.nome + '" data-ligado="' + p.na_cadeia + '">' +
        (p.na_cadeia ? L('na cadeia', 'in chain') : L('fora', 'out')) + '</button></div></div>';
    }).join('')
      : '<p class="vazio">' + L('vazio', 'empty') + '</p>') +
    '</div></div>').join('') : '<p class="vazio">' + T('prov.vazio') + '</p>';

  document.querySelectorAll('.prov').forEach(el => {
    el.addEventListener('dragstart', ev => {
      el.classList.add('arrastando');
      ev.dataTransfer.setData('text/plain', el.dataset.prov);
    });
    el.addEventListener('dragend', () => el.classList.remove('arrastando'));
  });
  // O último recurso não recebe arrasto.
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
        recado('recado-prov', quem + L(' foi para o tier ', ' moved to tier ') + faixa.dataset.tier + '.');
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
      recado('recado-prov', quem + (dentro ? L(' saiu da cadeia.', ' left the chain.') : L(' entrou na cadeia.', ' joined the chain.')));
    } catch (e) { recado('recado-prov', e.message); }
  }));
}

/* — Modelos por provedor — */
let modelosDeTodos = false;

function desenharModelos() {
  // Por padrão, mostra só quem está roteando.
  $('filtro-modelos').innerHTML =
    '<button class="aba" type="button" data-todos="false" aria-pressed="' + !modelosDeTodos + '">' + L('Na cadeia', 'In chain') + '</button>' +
    '<button class="aba" type="button" data-todos="true" aria-pressed="' + modelosDeTodos + '">' + L('Todos do catálogo', 'Full catalog') + '</button>';
  document.querySelectorAll('[data-todos]').forEach(b => b.addEventListener('click', () => {
    modelosDeTodos = b.dataset.todos === 'true';
    desenharModelos();
  }));

  // Provedor sem lista também precisa poder receber o primeiro modelo.
  const lista = (config.provedores || [])
    // O último recurso não tem modelo configurável.
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
      : '<p class="vazio">' + L('Sem lista própria: o provedor usa o modelo padrão dele.', 'No custom list: the provider uses its default model.') + '</p>';
    return '<div class="provlinha"><div class="topo">' + logo(p.nome) +
      '<span class="quem">' + (p.label || p.nome) + '</span>' +
      '<span class="obs">' + (p.modelos_proprios ? L('ordem sua', 'your order') : L('ordem de fábrica', 'factory order')) +
      '<button type="button" class="descobrir" data-descobre="' + p.nome + '">' + L('ver o que ele tem', 'see what it has') + '</button></span></div>' +
      '<div class="modelos">' + linhas + '</div>' +
      '<div class="achados" id="achados-' + p.nome + '"></div>' +
      '<form class="somar" data-prov="' + p.nome + '">' +
      '<input placeholder="' + L('id do modelo, como ele aparece na API', 'model id, as it appears in the API') + '" autocomplete="off" spellcheck="false">' +
      '<button type="submit" class="acao">' + L('adicionar', 'add') + '</button></form>' +
      '</div>';
  }).join('')
    : '<p class="vazio">' + (modelosDeTodos
        ? L('Nenhum provedor no catálogo.', 'No provider in the catalog.')
        : L('Nenhum provedor na cadeia. Veja o catálogo inteiro acima.', 'No provider in the chain. See the full catalog above.')) + '</p>';

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
      if (atual.indexOf(id) >= 0) { recado('recado-mod', id + L(' já está na lista.', ' is already in the list.')); return; }
      campo.value = '';
      trocarModelos(f.dataset.prov, atual.concat([id]));
    }));

  document.querySelectorAll('[data-descobre]').forEach(b =>
    b.addEventListener('click', async () => {
      const quem = b.dataset.descobre;
      const caixa = $('achados-' + quem);
      b.textContent = L('perguntando…', 'asking…');
      try {
        const r = await (await fetch('modelos/' + quem)).json();
        const achados = (r.models || r.modelos || []).map(m => m.id || m.nome || m);
        const atual = listaDe(quem);
        const novos = achados.filter(m => atual.indexOf(m) < 0);
        // Escolhe sem substituir a ordem já configurada.
        caixa.innerHTML = novos.length
          ? '<p class="dica">' + quem + ' diz ter ' + achados.length +
            L(' modelos. Clique para acrescentar:', ' models. Click to add:') + '</p>' +
            novos.map(m => '<button type="button" class="achado" data-somar="' +
              quem + '|' + m + '">+ ' + m + '</button>').join('')
          : '<p class="dica">' + (achados.length
              ? L('Todos os ', 'All ') + achados.length + L(' já estão na sua lista.', ' are already in your list.')
              : quem + L(' não devolveu modelo nenhum.', ' did not return any model.')) + '</p>';
        caixa.querySelectorAll('[data-somar]').forEach(a =>
          a.addEventListener('click', () => {
            const partes = a.dataset.somar.split('|');
            trocarModelos(partes[0], listaDe(partes[0]).concat([partes[1]]));
          }));
      } catch (e) {
        caixa.innerHTML = '<p class="dica">' + L('não consegui perguntar ao ', 'could not ask ') + quem +
          L('. Normalmente é chave faltando na tela de Credenciais.', '. Usually a key is missing in Credentials.') + '</p>';
      }
      b.textContent = L('ver o que ele tem', 'see what it has');
    }));
}

async function trocarModelos(provedor, modelos) {
  try {
    await salvar('config/modelos', { provedor: provedor, modelos: modelos });
    await carregarConfig();
    recado('recado-mod', provedor + L(': tenta ', ': tries ') + modelos[0] + L(' primeiro.', ' first.'));
  } catch (e) { recado('recado-mod', e.message); }
}

/* — Conectar — */
function haQuanto(s) {
  if (s < 60) return L('agora', 'now');
  if (s < 3600) return L('há ', '') + Math.round(s / 60) + L(' min', ' min ago');
  return L('há ', '') + Math.round(s / 3600) + L('h', 'h ago');
}

function desenharAbas(escolhida) {
  $('abas').innerHTML = ferramentas.map(f =>
    '<button class="aba" type="button" data-id="' + f.id + '" aria-pressed="' +
    (f.id === escolhida) + '">' + f.label +
    // Mostra conexão recente direto na aba.
    (f.conexao && f.conexao.ativo ? ' <span class="ponto-ok" title="já chamou"></span>' : '') +
    '</button>').join('');

  const f = ferramentas.filter(x => x.id === escolhida)[0] || ferramentas[0];
  if (!f) return;
  const url = new URL(window.location.href);
  if (url.searchParams.get('tela') === 'conectar') {
    url.searchParams.set('ferramenta', f.id);
    window.history.replaceState({}, '', url);
  }
  $('arquivo').textContent = f.arquivo || '';
  $('config-texto').textContent = f.conteudo;
  $('como').textContent = f.como || '';

  const c = f.conexao;
  const caixa = $('conexao');
  if (caixa) {
    if (!c) {
      // Pode estar configurada e ociosa; aqui só sabemos que nada chegou.
      caixa.className = 'conexao';
      caixa.innerHTML = '<b>' + L('Nenhuma chamada ainda.', 'No calls yet.') + '</b> ' +
        L('Cole a configuração, use o agente uma vez e esta linha muda sozinha.',
          'Paste the config, use the agent once, and this line updates by itself.');
    } else {
      const quando = haQuanto(c.ha_segundos);
      const ctx = (c.contextos || []).length
        ? ' ' + L('Aprendendo em:', 'Learning in:') + ' ' + c.contextos.map(x => '<code>' + x + '</code>').join(', ') + '.'
        : '';
      caixa.className = 'conexao ' + (c.ativo ? 'viva' : 'fria');
      caixa.innerHTML = (c.ativo ? '<b>' + L('Conectado.', 'Connected.') + '</b> ' : '<b>' + L('Já conectou.', 'Connected before.') + '</b> ') +
        c.chamadas + (c.chamadas === 1 ? L(' chamada, ', ' call, ') : L(' chamadas, ', ' calls, ')) +
        L('a última ', 'last one ') + quando + '.' + ctx;
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
    throw new Error(erro.detail || L('falhou com status ', 'failed with status ') + r.status);
  }
  return r.json();
}

async function carregarCredito() {
  try {
    const d = await (await fetch('saldo')).json();
    const contas = d.contas || [];
    $('credito').innerHTML = contas.length ? contas.map(c => {
      const saldo = c.saldo_usd != null ? c.saldo_usd : c.saldo;
      const valor = saldo != null ? 'US$ ' + Number(saldo).toFixed(2)
        : c.limite != null ? L('limite ', 'limit ') + c.limite : (c.detalhe || '—');
      const baixo = saldo != null && Number(saldo) < 1;
      return '<div class="credito">' + logo(c.provedor || c.provider || '') +
        '<span>' + (c.conta || c.provedor || c.provider || '') + '</span>' +
        '<span class="valor' + (baixo ? ' baixo' : '') + '">' + valor + '</span></div>';
    }).join('') : '<p class="vazio">' + L('Nenhum provedor desta cadeia informa crédito restante.', 'No provider in this chain reports remaining credit.') + '</p>';
  } catch (e) {
    $('credito').innerHTML = '<p class="vazio">' + L('Não consegui consultar o crédito.', 'Could not read credit.') + '</p>';
  }
}

async function carregarHistorico() {
  try {
    const d = await (await fetch('historico?dias=30')).json();
    const resumo = d.resumo || [];
    if (!resumo.length) {
      $('historico').innerHTML =
        '<p class="vazio">' + L('Ainda não há dias registrados. Um dia vira uma barra aqui.', 'No recorded days yet. A day becomes a bar here.') + '</p>';
      return;
    }
    const legenda = '<div class="historico-legenda" aria-label="' + L('Legenda dos dias', 'Day legend') + '">' +
      '<span><i data-s="vazio"></i>' + L('sem chamadas', 'no calls') + '</span>' +
      '<span><i data-s="ok"></i>' + L('saudável', 'healthy') + '</span>' +
      '<span><i data-s="atencao"></i>' + L('instável', 'unstable') + '</span>' +
      '<span><i data-s="ruim"></i>' + L('com falha', 'failed') + '</span></div>';
    $('historico').innerHTML = legenda + resumo.map(r => {
      const faixa = (d.faixas || {})[r.provedor] || [];
      const barras = faixa.map(dia =>
        '<i data-s="' + dia.saude + '" title="' + dia.dia + ': ' + dia.ok + ' ok, ' +
        dia.err + L(' erro', ' error') + (dia.motivo ? ': ' + dia.motivo : '') + '"></i>').join('');
      const alertas = [];
      if (r.dias_de_atencao) alertas.push(r.dias_de_atencao + L(' instável', ' unstable'));
      if (r.dias_ruins) alertas.push(r.dias_ruins + L(' com falha', ' failed'));
      const nota = r.dias_com_uso + L(' dias usados · ', ' days used · ') +
        (alertas.length ? alertas.join(' · ') : L('todos saudáveis', 'all healthy')) +
        (r.pior_motivo ? ' · ' + r.pior_motivo : '');
      return '<div class="linhadia"><div class="topo">' + logo(r.provedor) +
        '<span>' + r.provedor + '</span>' +
        '<span class="up' + (r.uptime < 99 ? ' baixo' : '') + '">' + r.uptime + '%</span></div>' +
        '<div class="dias">' + barras + '</div>' +
        '<div class="legenda"><em>' + L('30 dias atrás', '30 days ago') + '</em><em>' + nota + '</em><em>' + L('hoje', 'today') + '</em></div></div>';
    }).join('');
  } catch (e) {
    $('historico').innerHTML = '<p class="vazio">' + L('Não consegui ler o histórico.', 'Could not read history.') + '</p>';
  }
}

async function carregarConfig() {
  config = await (await fetch('config')).json();
  // Idioma vem junto da configuração geral.
  if (config.idioma && config.idioma !== IDIOMA) {
    IDIOMA = config.idioma;
    traduzirPagina();
  }
  desenharIdioma();
  desenharEstrategia();
  desenharOrdemCadeia();
  desenharTiers();
  desenharReservados();
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
  // Atualiza a tela imediatamente após a escolha.
  IDIOMA = qual;
  traduzirPagina();
  desenharIdioma();
  await salvar('config/idioma', { valor: qual });
  // Redesenha o que e montado pelo JS e nao carrega `data-t`.
  desenharAgora();
  desenharEstrategia();
  desenharOrdemCadeia();
  desenharTiers();
  if (ferramentas.length) desenharAbas((document.querySelector('.aba[aria-pressed="true"]') || {}).dataset?.id);
  desenharReservados();
  desenharContas();
  carregarUso();
  carregarHistorico();
  carregarCredito();
  carregarJanelas();
}

async function atualizar() {
  try {
    const d = await (await fetch('painel/dados')).json();
    estado = d;
    desenharAgora();
    $('pulso').innerHTML = '<b>' + d.provedores.length + '</b> ' + L('na cadeia', 'in chain') + '<br>' +
      '<b>' + d.chamadas + '</b> ' + L('chamadas', 'calls');
    if (d.ferramentas) {
      // Redesenha porque a conexão pode mudar enquanto a tela está aberta.
      const escolhida = (document.querySelector('.aba[aria-pressed="true"]') || {}).dataset;
      ferramentas = d.ferramentas;
      const pedida = new URLSearchParams(window.location.search).get('ferramenta');
      desenharAbas((escolhida && escolhida.id) || pedida || (ferramentas[0] && ferramentas[0].id));
    }
  } catch (e) { $('pulso').textContent = L('servidor fora do ar', 'server offline'); }
}

let contasDeTodos = false;
let contas = { contas: [], tiers: {}, alvos: {} };

async function carregarCredenciais() {
  try {
    contas = await (await fetch('contas')).json();
    const d = await (await fetch('credenciais')).json();
    $('onde-cofre').textContent = d.cofre ? L('Cofre desta máquina: ', 'Vault on this machine: ') + d.cofre : '';
    $('trazer-ambiente').hidden = !(d.credenciais || []).some(c => c.origem === 'ambiente');
  } catch (e) { $('credenciais').textContent = L('não consegui ler as contas', 'could not read accounts'); return; }

  desenharReservados();
  desenharContas();
  desenharFormDeConta();
  ligarImportacao();
}

function desenharReservados() {
  const alvos = contas.alvos || {};
  if (!alvos.ultra) { $('reservados').innerHTML = ''; return; }
  const disponiveis = (contas.contas || []).filter(c => c.configurada);
  const porId = new Map(disponiveis.map(c => [c.id, c]));
  const ordem = (contas.reforcado || []).filter(id => porId.has(id));
  const fora = disponiveis.filter(c => !ordem.includes(c.id));

  $('reservados').innerHTML = '<h2>' + T('cred.reforcado') + ' <span class="risco"></span></h2>' +
    '<div class="reforcado-card"><p>' + T('cred.ref_desc') + '</p>' +
    (ordem.length ? '<ol class="lista-cadeia lista-reforcado">' + ordem.map((id, i) => {
      const c = porId.get(id);
      return '<li>' + logo(c.provider) + '<span>' + c.label +
        (c.paga ? ' <small>' + L('paga', 'paid') + '</small>' : '') + '</span><code>' + c.id + '</code>' +
        '<span class="mover">' +
        '<button type="button" data-ref-move="-1" data-indice="' + i +
        '" aria-label="' + L('Subir ', 'Move up ') + c.label + '"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" data-ref-move="1" data-indice="' + i +
        '" aria-label="' + L('Descer ', 'Move down ') + c.label + '"' + (i === ordem.length - 1 ? ' disabled' : '') + '>↓</button>' +
        '<button type="button" class="apagar" data-ref-remove="' + i +
        '" aria-label="' + L('Remover ', 'Remove ') + c.label + '">×</button></span></li>';
    }).join('') + '</ol>' : '<p class="vazio compacto">' + L('Nenhuma conta escolhida.', 'No account selected.') + '</p>') +
    (fora.length ? '<div class="adicionar-ref"><select id="ref-conta">' +
      fora.map(c => '<option value="' + c.id + '">' + c.label +
        (c.paga ? ' · ' + L('paga', 'paid') : '') + '</option>').join('') + '</select>' +
      '<button type="button" class="acao" id="ref-adicionar">' + L('adicionar', 'add') + '</button></div>' : '') +
    '<p class="como">' + T('cred.ref_header') +
    ' <code>X-RobinBandit-Mode: reinforced</code>.</p></div>';

  const salvarOrdem = async nova => {
    const r = await fetch('contas/reforcado', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contas: nova }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || L('não deu', 'failed'));
    contas.reforcado = (await r.json()).contas;
    desenharReservados();
    recado('recado-prov', L('Nova ordem aplicada na próxima chamada.', 'New order applies to the next call.'));
  };
  document.querySelectorAll('[data-ref-move]').forEach(botao =>
    botao.addEventListener('click', async () => {
      const de = Number(botao.dataset.indice);
      const para = de + Number(botao.dataset.refMove);
      const nova = ordem.slice();
      [nova[de], nova[para]] = [nova[para], nova[de]];
      try { await salvarOrdem(nova); } catch (e) { recado('recado-prov', e.message); }
    }));
  document.querySelectorAll('[data-ref-remove]').forEach(botao =>
    botao.addEventListener('click', async () => {
      const nova = ordem.filter((_, i) => i !== Number(botao.dataset.refRemove));
      try { await salvarOrdem(nova); } catch (e) { recado('recado-prov', e.message); }
    }));
  if ($('ref-adicionar')) $('ref-adicionar').addEventListener('click', async () => {
    try { await salvarOrdem([...ordem, $('ref-conta').value]); }
    catch (e) { recado('recado-prov', e.message); }
  });
}

function desenharContas() {
  $('filtro-cred').innerHTML =
    '<button class="aba" type="button" data-cred="false" aria-pressed="' + !contasDeTodos + '">' + L('Configuradas', 'Configured') + '</button>' +
    '<button class="aba" type="button" data-cred="true" aria-pressed="' + contasDeTodos + '">' + L('Todas', 'All') + '</button>';
  document.querySelectorAll('[data-cred]').forEach(b => b.addEventListener('click', () => {
    contasDeTodos = b.dataset.cred === 'true';
    desenharContas();
  }));

  const lista = (contas.contas || [])
    // O último recurso não tem conta própria.
    .filter(c => c.provider !== 'fallback')
    .filter(c => contasDeTodos || c.configurada);
  if (!lista.length) {
    $('credenciais').innerHTML = '<p class="vazio">' + (contasDeTodos
      ? L('Nenhuma conta no catálogo.', 'No account in the catalog.')
      : L('Nenhuma conta configurada ainda. Veja todas acima e cole uma chave.', 'No account configured yet. See all above and paste a key.')) + '</p>';
    return;
  }

  const porProvedor = {};
  lista.forEach(c => (porProvedor[c.provider] = porProvedor[c.provider] || []).push(c));

  $('credenciais').innerHTML = Object.keys(porProvedor).sort().map(prov =>
    '<div class="grupo-cred"><h2>' + logo(prov) + prov + '</h2>' +
    porProvedor[prov].map(c => {
      // CLI oficial autentica fora do cofre.
      if (c.por_cli) {
        const qual = c.auth_type === 'codex_cli' ? 'Codex CLI' : 'Claude Code';
        const comando = c.auth_type === 'codex_cli' ? 'codex login' : 'claude';
        return '<div class="cred"><div class="topo">' +
          '<span class="var">' + c.label + '</span>' +
          '<span class="estado' + (c.configurada ? ' tem' : '') + '">' +
          (c.configurada ? L('autenticado', 'authenticated') : L('não conectado', 'not connected')) + '</span></div>' +
          '<p class="cli">' + L('Quem autentica é o ', 'Authentication is handled by ') + '<b>' + qual + '</b>, ' +
          L('com a assinatura que você já usa. O RobinBandit não lê nem renova credencial. Ele só chama o executável.',
            'with the subscription you already use. RobinBandit does not read or renew credentials. It only calls the executable.') +
          // Mostra detalhe só quando ele acrescenta informação.
          (c.detalhe && c.detalhe !== 'autenticado' ? ' <em>' + c.detalhe + '</em>' : '') +
          (c.configurada ? '' : L(' Rode ', ' Run ') + '<code>' + comando + '</code>' + L(' no terminal e recarregue.', ' in the terminal and reload.')) +
          '</p></div>';
      }
      // A marca de paga é da chave, não da variável inteira.
      const chaves = (c.chaves || []).map(k =>
        '<span class="chave' + (k.paga ? ' e-paga' : '') + '">' +
        '<b' + (k.nome ? '' : ' class="anonima"') + '>' + (k.nome || L('sem nome', 'unnamed')) + '</b>' +
        '<span class="dica">' + k.dica + '</span>' +
        '<button type="button" class="marca-paga' + (k.paga ? '' : ' off') + '" data-paga="' +
        c.key_env + '" data-i="' + k.i + '" data-vale="' + (k.paga ? '1' : '0') +
        '" title="' + (k.paga ? L('crédito pago; clique para desmarcar', 'paid credit; click to unmark') : L('marcar como crédito pago', 'mark as paid credit')) +
        '">' + L('paga', 'paid') + '</button>' +
        '<span class="acoes">' +
        '<button type="button" data-renomear="' + c.key_env + '" data-i="' + k.i +
        '" data-nome="' + (k.nome || '') + '" title="' + L('dar um nome a esta chave', 'name this key') + '">&#9998;</button>' +
        '<button type="button" class="apagar" data-apagar="' + c.key_env + '" data-i="' + k.i +
        '" title="' + L('remover esta chave', 'remove this key') + '">&times;</button></span>' +
        '</span>').join('');
      return '<div class="cred">' +
        '<div class="topo">' +
        '<span class="var">' + c.key_env + '</span>' +
        (c.label && c.label !== c.provider ? '<span class="conta-nome">' + c.label + '</span>' : '') +
        '<span class="estado' + (c.configurada ? ' tem' : '') + '">' +
        (c.configurada ? c.origem : L('sem chave', 'no key')) + '</span>' +
        '</div>' +
        (chaves ? '<div class="chaves">' + chaves + '</div>' : '') +
        '<form data-var="' + c.key_env + '">' +
        '<input class="valor" type="password" placeholder="' +
        (c.configurada ? L('adicionar outra chave', 'add another key') : L('colar a chave', 'paste the key')) +
        '" autocomplete="off" spellcheck="false">' +
        '<input class="apelido" placeholder="' + L('apelido, ex.: conta pessoal', 'nickname, e.g. personal account') + '" autocomplete="off">' +
        '<label class="paga"><input type="checkbox" class="e-paga"> ' + L('crédito pago', 'paid credit') + '</label>' +
        '<button type="submit" class="acao">' + L('guardar no cofre', 'save to vault') + '</button>' +
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
        if (!r.ok) throw new Error((await r.json()).detail || L('não deu', 'failed'));
        // O valor nunca volta para a tela.
        campo.value = '';
        apelido.value = '';
        paga.checked = false;
        recado('recado-cred', f.dataset.var + L(' guardada no cofre.', ' saved to the vault.'));
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
      const nome = prompt(L('Nome desta chave (para você saber qual é qual):', 'Name this key (so you know which is which):'), atual);
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
        recado('recado-cred', L('Removida do cofre. O ambiente não foi tocado.', 'Removed from the vault. The environment was not touched.'));
        carregarCredenciais();
      } catch (e) { recado('recado-cred', e.message); }
    }));
}

function milhar(n) {
  // Compacta números grandes para leitura rápida.
  const decimal = IDIOMA === 'pt' ? ',' : '.';
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.', decimal) + L(' bi', 'B');
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', decimal) + L(' mi', 'M');
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace('.', decimal) + L(' mil', 'k');
  return String(n);
}

function dolar(n) {
  return new Intl.NumberFormat(IDIOMA === 'pt' ? 'pt-BR' : 'en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2,
    maximumFractionDigits: Number(n || 0) < 0.01 ? 4 : 2
  }).format(Number(n || 0));
}

const MESES_PT = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const MESES_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SEMANA_PT = ['', 'seg', '', 'qua', '', 'sex', ''];
const SEMANA_EN = ['', 'Mon', '', 'Wed', '', 'Fri', ''];

function calendarioDe(dias) {
  // Alinha a grade pelo domingo da primeira semana.
  const primeiro = new Date(dias[0].dia + 'T00:00:00Z');
  const vazios = primeiro.getUTCDay();
  const pico = Math.max(1, ...dias.map(x => x.total));

  const celulas = [];
  for (let i = 0; i < vazios; i++) celulas.push('<i class="fora"></i>');
  dias.forEach(x => {
    const n = x.total === 0 ? 0 : Math.min(4, Math.ceil(x.total / pico * 4));
    const quanto = x.total
      ? milhar(x.total) + L(' tokens em ', ' tokens in ') + x.chamadas + (x.chamadas === 1 ? L(' chamada', ' call') : L(' chamadas', ' calls'))
      : L('sem uso', 'no usage');
    celulas.push('<i data-n="' + n + '" title="' + x.dia + ': ' + quanto + '"></i>');
  });

  // Um rótulo por mês, agrupado por colunas.
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
    // Mês estreito demais fica sem rótulo.
    rotulos.map(r => '<span>' + (r.largura > 2 ? (IDIOMA === 'pt' ? MESES_PT : MESES_EN)[r.mes] : '') + '</span>').join('') +
    '</div>' +
    '<div class="semana">' + (IDIOMA === 'pt' ? SEMANA_PT : SEMANA_EN).map(d => '<span>' + d + '</span>').join('') + '</div>' +
    '<div class="malha">' + celulas.join('') + '</div>' +
    '</div>' +
    '<div class="legenda"><b>' + L('menos', 'less') + '</b>' +
    [0, 1, 2, 3, 4].map(n => '<i data-n="' + n + '"></i>').join('') +
    '<b style="margin-left:4px">' + L('mais', 'more') + '</b>' +
    '<span class="fim">' + L('cada quadrado é um dia; o mais escuro é o dia em que você mais gastou',
      'each square is one day; the darkest one is the day you spent the most') + '</span>' +
    '</div>';
}

async function carregarUso() {
  let d;
  desenharPeriodosUso();
  try { d = await (await fetch('uso?dias=' + periodoUso)).json(); }
  catch (e) { $('uso-calendario').textContent = L('não consegui ler o uso', 'could not read usage'); return; }

  const mes = d.periodo || d.total || {};
  const tudo = d.periodo || d.total || {};
  const dias = d.calendario || [];
  const gastou = (tudo.total || 0) > 0;

  // Sem dados, mostra explicação em vez de métricas zeradas.
  const comCusto = mes.chamadas_com_custo || 0;
  $('uso-numeros').innerHTML = gastou
    ? '<div><b class="verde">' + milhar(mes.entrada || 0) + '</b><span>' + L('entrada', 'input') + '</span>' +
      '<small>' + L('tokens nos últimos ', 'tokens in the last ') + periodoUso + L(' dias', ' days') + '</small></div>' +
      '<div><b>' + milhar(mes.saida || 0) + '</b><span>' + L('saída', 'output') + '</span>' +
      '<small>' + (mes.cacheado ? milhar(mes.cacheado) + L(' tokens vieram do cache', ' tokens came from cache') : L('tokens nos últimos ', 'tokens in the last ') + periodoUso + L(' dias', ' days')) + '</small></div>' +
      '<div><b class="ambar">' + (comCusto ? dolar(mes.custo_usd) : L('não informado', 'not reported')) + '</b><span>' + L('custo em USD', 'cost in USD') + '</span>' +
      '<small>' + (comCusto ? L('informado em ', 'reported in ') + comCusto + L(' de ', ' of ') + mes.chamadas + L(' chamadas', ' calls') : L('nenhum provedor enviou preço', 'no provider reported price')) + '</small></div>' +
      '<div><b>' + (mes.chamadas || 0) + '</b><span>' + L('chamadas', 'calls') + '</span>' +
      '<small>' + milhar(mes.total || 0) + L(' tokens no total', ' total tokens') + '</small></div>'
    : '';

  $('uso-tendencia').innerHTML = gastou ? graficoTendencia(dias) : '';
  $('uso-periodo-titulo').textContent = periodoUso === 365 ? L('Seu ano', 'Your year') : L('Dias do período', 'Days in period');

  $('uso-calendario').innerHTML = gastou
    ? calendarioDe(dias)
    : '<div class="sem-uso"><b>' + L('Nenhum turno medido ainda', 'No measured turn yet') + '</b><span>' +
      L('A contagem começa na primeira resposta que passar por aqui. Aponte sua ferramenta para este endereço na tela Conectar. Só entra no gráfico quem informa o consumo junto da resposta.',
        'Counting starts with the first response that passes through here. Point your tool to this address on Connect. The chart only includes providers that report usage with the response.') + '</span></div>';

  const linhas = d.por_provedor || [];
  const maior = Math.max(1, ...linhas.map(x => x.total));
  $('uso-detalhe').hidden = !linhas.length;
  $('uso-provedores').innerHTML = linhas.map(x =>
    '<div class="gasto">' + logo(x.provedor) +
    '<span class="quem">' + x.provedor + '</span>' +
    '<span class="barra"><span style="width:' + Math.round(x.total / maior * 100) + '%"></span></span>' +
    '<span class="detalhe">' + milhar(x.entrada) + ' ' + L('entrada', 'input') + '<br>' + milhar(x.saida) + ' ' + L('saída', 'output') + '</span>' +
    '<span class="n">' + milhar(x.total) + '<small>' +
      (x.chamadas_com_custo ? dolar(x.custo_usd) : L('custo não informado', 'cost not reported')) +
    '</small></span></div>').join('');
}

async function carregarJanelas() {
  let d;
  try { d = await (await fetch('janelas')).json(); }
  catch (e) { $('janelas').textContent = L('não consegui ler as janelas', 'could not read windows'); return; }

  const linhas = d.janelas || [];
  $('janelas').innerHTML = linhas.length ? linhas.map(j => {
    if (!j.aberta) {
      return '<div class="janela parada"><div class="topo">' + logo(j.provedor) +
        '<span class="quem">' + j.provedor + '</span>' +
        '<span class="quanto"><small>' + L('bloco fechado', 'closed block') + '</small></span></div>' +
        '<p class="conta">' + L('Nenhuma chamada na janela atual. A próxima abre um bloco de ',
          'No call in the current window. The next one opens a ') +
        j.horas + L('h.', 'h block.') + '</p></div>';
    }
    const pct = Math.round(j.fracao * 100);
    // Acima de 80%, destaca proximidade do limite.
    const perto = j.fracao >= 0.8 ? ' perto' : '';
    return '<div class="janela"><div class="topo">' + logo(j.provedor) +
      '<span class="quem">' + j.provedor + '</span>' +
      '<span class="quanto">' + j.vira_em + ' <small>' + L('para virar', 'to roll over') + '</small></span></div>' +
      '<div class="trilho"><div class="cheio' + perto + '" style="width:' + pct + '%"></div></div>' +
      '<p class="conta">' + j.chamadas + (j.chamadas === 1 ? L(' chamada', ' call') : L(' chamadas', ' calls')) +
      L(' neste bloco de ', ' in this ') + j.horas + L('h', 'h block') +
      (j.bloqueios ? ' · <b>' + L('parou por limite ', 'stopped by limit ') + j.bloqueios + 'x</b>' : '') +
      (j.erros ? ' · ' + j.erros + (j.erros === 1 ? L(' erro', ' error') : L(' erros', ' errors')) : '') +
      '</p></div>';
  }).join('')
    : '<p class="vazio">' + L('Nenhum provedor de assinatura na cadeia. Janela é coisa de assinatura: quem cobra por token tem limite por minuto, e disso o roteador já cuida sozinho.',
      'No subscription provider in the chain. Windows are for subscriptions: token-billed providers have per-minute limits, and the router already handles those.') + '</p>';

  const p = d.ping || {};
  $('ping').innerHTML =
    '<div class="topo"><h2>' + L('Perguntar se a cota já voltou', 'Ask whether quota is back') + '</h2>' +
    '<button type="button" class="acao liga-ping" id="btn-ping">' +
    (p.ativo ? L('desligar', 'turn off') : L('ligar', 'turn on')) + '</button></div>' +
    '<p>' + L('O cooldown vence por tempo, não por evidência: se a cota voltou antes, o roteador continua ignorando o provedor; se não voltou, quem descobre é o seu próximo turno. O ping é uma chamada mínima, fora de um turno, só para saber. Custa uma chamada e por isso vem desligado.',
      'Cooldown expires by time, not evidence: if quota returned earlier, the router keeps ignoring the provider; if it did not, your next turn discovers it. Ping is a minimal call outside a turn, only to check. It costs one call, so it starts off.') + '</p>' +
    '<div class="campos">' +
    '<label>' + L('a cada ', 'every ') + '<input type="number" id="ping-intervalo" min="60" step="30" value="' +
    Math.round(p.intervalo_s || 300) + '"> ' + L('segundos', 'seconds') + '</label>' +
    '<label><input type="checkbox" id="ping-cooldown"' + (p.so_em_cooldown ? ' checked' : '') +
    '> ' + L('apenas provedores em cooldown', 'only providers in cooldown') + '</label>' +
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
    if (!r.ok) throw new Error(L('não deu', 'failed'));
    recado('recado-janela', L('Pronto.', 'Done.'));
    carregarJanelas();
  } catch (e) { recado('recado-janela', e.message); }
}

function ligarImportacao() {
  const b = $('btn-importar');
  if (!b || b.dataset.pronto) return;
  b.dataset.pronto = '1';
  b.addEventListener('click', async () => {
    b.disabled = true;
    b.textContent = L('trazendo…', 'importing…');
    try {
      const d = await (await fetch('credenciais/importar', { method: 'POST' })).json();
      recado('recado-cred', d.trazidas.length
        ? d.trazidas.length + L(' no cofre: ', ' in the vault: ') + d.trazidas.join(', ')
        : L('Nada novo: o cofre já tem tudo que o ambiente tinha.', 'Nothing new: the vault already has everything the environment had.'));
      carregarCredenciais();
    } catch (e) { recado('recado-cred', L('não consegui trazer', 'could not import')); }
    b.disabled = false;
    b.textContent = L('trazer para o cofre', 'import to vault');
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
    if (!corpo.id || !corpo.variavel) { recado('recado-cred', L('Falta o apelido ou o nome da variável.', 'Nickname or variable name is missing.')); return; }
    try {
      const r = await fetch('contas', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      });
      if (!r.ok) throw new Error((await r.json()).detail || L('não deu', 'failed'));
      $('conta-id').value = ''; $('conta-var').value = ''; $('conta-paga').checked = false;
      recado('recado-cred', L('Conta criada. Agora cole a chave dela abaixo.', 'Account created. Now paste its key below.'));
      contasDeTodos = true;
      carregarCredenciais();
    } catch (e) { recado('recado-cred', e.message); }
  });
}

const TELAS = ['agora', 'provedores', 'modelos', 'credenciais', 'janelas', 'uso', 'conectar'];

/* Navegação entre telas. */
function trocarTela(qual) {
  if (!TELAS.includes(qual)) qual = 'agora';
  document.querySelectorAll('nav button[data-tela]').forEach(b => {
    // O CSS realça apenas `aria-current="page"`.
    if (b.dataset.tela === qual) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  TELAS.forEach(t => $('tela-' + t).classList.toggle('oculto', t !== qual));
  const url = new URL(window.location.href);
  if (qual === 'agora') url.searchParams.delete('tela');
  else url.searchParams.set('tela', qual);
  if (qual !== 'conectar') url.searchParams.delete('ferramenta');
  window.history.replaceState({}, '', url);
}

function desenharPeriodosUso() {
  const rotulos = {
    7: L('7 dias', '7 days'),
    30: L('30 dias', '30 days'),
    90: L('90 dias', '90 days'),
    365: L('1 ano', '1 year'),
  };
  $('uso-periodos').innerHTML = Object.keys(rotulos).map(n =>
    '<button class="aba" type="button" data-periodo="' + n + '" aria-pressed="' +
    (Number(n) === periodoUso) + '">' + rotulos[n] + '</button>'
  ).join('');
  $('uso-periodos').querySelectorAll('[data-periodo]').forEach(b =>
    b.addEventListener('click', () => {
      periodoUso = Number(b.dataset.periodo);
      carregarUso();
    }));
}

function graficoTendencia(dias) {
  if (!dias.length) return '';
  const largura = 800, altura = 150, margem = 18;
  const pico = Math.max(1, ...dias.map(d => Number(d.total || 0)));
  const x = i => margem + (dias.length === 1 ? 0 : i / (dias.length - 1) * (largura - margem * 2));
  const y = valor => altura - margem - Number(valor || 0) / pico * (altura - margem * 2);
  const pontos = dias.map((d, i) => x(i).toFixed(1) + ',' + y(d.total).toFixed(1)).join(' ');
  const area = margem + ',' + (altura - margem) + ' ' + pontos + ' ' +
    x(dias.length - 1).toFixed(1) + ',' + (altura - margem);
  const melhor = dias.reduce((a, b) => Number(a.total || 0) >= Number(b.total || 0) ? a : b);
  return '<div class="tendencia-topo"><span>' + L('Tokens por dia', 'Tokens per day') + '</span><b>' +
    L('pico de ', 'peak of ') + milhar(melhor.total || 0) + L(' em ', ' on ') + melhor.dia + '</b></div>' +
    '<svg viewBox="0 0 ' + largura + ' ' + altura + '" role="img" aria-label="' + L('Tendência de tokens no período', 'Token trend in the period') + '">' +
    '<defs><linearGradient id="area-verde" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0" stop-color="#7C9A7F" stop-opacity=".32"/><stop offset="1" stop-color="#7C9A7F" stop-opacity="0"/></linearGradient></defs>' +
    '<line x1="' + margem + '" y1="' + (altura - margem) + '" x2="' + (largura - margem) + '" y2="' + (altura - margem) + '"/>' +
    '<polygon points="' + area + '"/><polyline points="' + pontos + '"/></svg>' +
    '<div class="tendencia-eixo"><span>' + dias[0].dia + '</span><span>' + dias[dias.length - 1].dia + '</span></div>';
}

document.querySelectorAll('nav button[data-tela]').forEach(b =>
  b.addEventListener('click', () => trocarTela(b.dataset.tela)));

$('copiar-config').addEventListener('click', async () => {
  const botao = $('copiar-config');
  const texto = $('config-texto').textContent;
  try {
    await navigator.clipboard.writeText(texto);
    botao.textContent = T('con.copiado');
    window.setTimeout(() => { botao.textContent = T('con.copiar'); }, 1400);
  } catch (e) {
    recado('conexao', L('Não consegui copiar. Selecione o bloco e copie manualmente.',
      'Could not copy. Select the block and copy it manually.'));
  }
});

trocarTela(new URLSearchParams(window.location.search).get('tela') || 'agora');

carregarConfig().catch(() => recado('recado-prov', L('não consegui ler a configuração', 'could not read configuration')));
carregarCredito();
carregarCredenciais();
carregarJanelas();
carregarUso();
carregarHistorico();
atualizar();
setInterval(atualizar, 4000);
