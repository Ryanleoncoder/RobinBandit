const $ = id => document.getElementById(id);
let config = null;
let ferramentas = [];
let estado = { provedores: [], ordem: [], atividade: [] };
let periodoUso = 30;

function logo(nome) {
  const sigla = (nome || '?').slice(0, 2).toUpperCase();
  return '<img class="logo" src="logos/' + nome + '.svg" alt="" ' +
    'onerror="this.outerHTML=\'<span class=&quot;logo falta&quot;>' + sigla + '</span>\'">';
}

function selo(p) {
  // Derivado dos contadores persistidos, não do status inicial do processo.
  if (p.cooldown) return ['mau', 'em espera'];
  const ok = p.ok || 0, err = p.err || 0, total = ok + err;
  if (!total) return ['', 'sem uso'];
  const taxa = ok / total;
  if (taxa >= 0.95) return ['bom', 'saudável'];
  if (taxa >= 0.7) return ['atencao', 'instável'];
  return ['mau', 'falhando'];
}

function medidor(valor, estimado) {
  // Sem histórico, o número é o prior do catálogo.
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
    '<span>primeiro da fila</span>' +
    '<small>' + T('prov.modo.' + (estado.estrategia || 'adaptive')) +
    (primeiro && primeiro.motivo ? ': ' + primeiro.motivo : '') + '</small></div>' +
    '<div><b>' + chamadas + '</b><span>chamadas</span>' +
    '<small>desde que o servidor subiu</small></div>' +
    '<div><b' + (emEspera ? ' class="ambar"' : '') + '>' + dePe + ' de ' + total + '</b>' +
    '<span>de pé</span><small>' +
    (emEspera ? emEspera + ' em espera depois de falhar' : 'ninguém em espera') + '</small></div>' +
    '<div><b' + (abertas.length ? ' class="ambar"' : '') + '>' + abertas.length + '</b>' +
    '<span>em andamento</span><small>' + (ultima
      ? (ultima.status === 'em_andamento' ? 'roteando agora' : 'atividade ' + haQuanto(ultima.ha_segundos))
      : 'nenhuma desde que subiu') + '</small></div>';

  desenharAtividade(atividade);

  // Uma tabela combina ordem e saúde.
  $('ordem').innerHTML = linhas.length
    ? '<table><thead><tr><th></th><th>Provedor</th><th>Estado</th><th>Qualidade</th>' +
      '<th>OK / erro</th><th>Latência</th><th>Cota</th><th>Por quê</th></tr></thead><tbody>' +
      linhas.map((l, i) => {
        const s = saude[l.nome] || {};
        const par = selo(s);
        const espera = s.cooldown ? ' <span class="num" style="color:var(--ambar)">' + s.cooldown + 's</span>' : '';
        const recente = s.em_andamento
          ? '<span class="agora">respondendo agora</span>'
          : s.ultimo_modelo
            ? s.ultimo_modelo + (s.ha_segundos != null ? ' · ' + haQuanto(s.ha_segundos) : '')
            : l.motivo;
        const cota = s.rpm_restante != null
          ? s.rpm_restante + ' rpm'
          : s.rpd_restante != null ? s.rpd_restante + ' dia' : '—';
        return '<tr><td class="posicao">' + (i + 1) + '</td>' +
          '<td><span class="comlogo">' + logo(l.nome) + l.nome + '</span></td>' +
          '<td><span class="selo ' + par[0] + '">' + par[1] + '</span>' + espera + '</td>' +
          '<td>' + medidor(l.qualidade_num, l.estimado) + '</td>' +
          '<td class="num">' + (s.ok || 0) + (s.err ? ' / <span style="color:var(--ruim)">' + s.err + '</span>' : ' / 0') + '</td>' +
          '<td class="num">' + l.latencia + '</td>' +
          '<td class="num cota">' + cota + '</td>' +
          '<td class="porque">' + recente + '</td></tr>';
      }).join('') + '</tbody></table>'
    : '<p class="vazio" style="padding:22px">Nenhuma chamada ainda. A fila aparece depois do primeiro turno.</p>';
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
        recado('recado-prov', 'Vale a partir da próxima chamada.');
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
  if (modo === 'hybrid') return 'Reforçado';
  if (modo === 'strict') return 'Dedicado';
  return 'Normal';
}

function desenharAtividade(itens) {
  const onde = $('atividade');
  const fluxo = $('fluxo');
  const atual = itens.find(a => a.status === 'em_andamento') || itens[0];
  if (!atual) {
    fluxo.innerHTML = '<div class="fluxo-vazio">A fila está pronta. A próxima tentativa aparece aqui enquanto acontece.</div>';
    onde.innerHTML = '<p class="vazio">Nenhuma tentativa desde que o servidor subiu.</p>';
    return;
  }

  const viva = atual.status === 'em_andamento';
  const contexto = atual.contexto ? '<code>' + atual.contexto + '</code>' : 'contexto padrão';
  const modo = nomeModoChamada(atual.modo);
  fluxo.innerHTML = '<div class="fluxo-cabeca"><span class="ao-vivo' + (viva ? ' ligado' : '') + '">' +
    (viva ? 'ao vivo' : 'mais recente') + '</span><span>' + modo + ' · ' + contexto + '</span></div>' +
    '<div class="rota-viva"><b>RobinBandit</b><span class="fio' + (viva ? ' correndo' : '') + '"><i></i></span>' +
    '<span class="destino">' + logo(atual.provedor) + '<b>' + atual.provedor + '</b></span></div>' +
    '<p>' + (viva ? 'Aguardando resposta' : atual.status === 'sucesso' ? 'Resposta concluída' : 'Tentativa encerrada') +
    (atual.modelo ? ' com <code>' + atual.modelo + '</code>' : '') + '.</p>';

  onde.innerHTML = itens.slice(0, 4).map(a => {
    const classe = a.status === 'sucesso' ? 'ok' : a.status === 'falha' ? 'erro' : 'rodando';
    const duracao = a.duracao_ms != null ? a.duracao_ms + ' ms' : 'agora';
    const detalhe = [a.modelo || a.contexto, usoCurto(a.uso), a.motivo].filter(Boolean).join(' · ');
    return '<div class="atividade-linha"><span class="atividade-estado ' + classe + '"></span>' +
      logo(a.provedor) + '<span class="atividade-quem"><b>' + a.provedor + '</b><small>' +
      (detalhe || 'tentativa em andamento') + '</small></span>' +
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
        '<button type="button" data-move="-1" data-indice="' + i + '" aria-label="Subir ' + nome + '"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" data-move="1" data-indice="' + i + '" aria-label="Descer ' + nome + '"' + (i === nomes.length - 1 ? ' disabled' : '') + '>↓</button>' +
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
      recado('recado-prov', 'Nova ordem aplicada.');
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
        (p.na_cadeia ? 'na cadeia' : 'fora') + '</button></div></div>';
    }).join('')
      : '<p class="vazio">vazio</p>') +
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
  // Por padrão, mostra só quem está roteando.
  $('filtro-modelos').innerHTML =
    '<button class="aba" type="button" data-todos="false" aria-pressed="' + !modelosDeTodos + '">Na cadeia</button>' +
    '<button class="aba" type="button" data-todos="true" aria-pressed="' + modelosDeTodos + '">Todos do catálogo</button>';
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
      : '<p class="vazio">Sem lista própria: o provedor usa o modelo padrão dele.</p>';
    return '<div class="provlinha"><div class="topo">' + logo(p.nome) +
      '<span class="quem">' + (p.label || p.nome) + '</span>' +
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
        // Escolhe sem substituir a ordem já configurada.
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
          '. Normalmente é chave faltando na tela de Credenciais.</p>';
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
      const saldo = c.saldo_usd != null ? c.saldo_usd : c.saldo;
      const valor = saldo != null ? 'US$ ' + Number(saldo).toFixed(2)
        : c.limite != null ? 'limite ' + c.limite : (c.detalhe || '—');
      const baixo = saldo != null && Number(saldo) < 1;
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
    const legenda = '<div class="historico-legenda" aria-label="Legenda dos dias">' +
      '<span><i data-s="vazio"></i>sem chamadas</span>' +
      '<span><i data-s="ok"></i>saudável</span>' +
      '<span><i data-s="atencao"></i>instável</span>' +
      '<span><i data-s="ruim"></i>com falha</span></div>';
    $('historico').innerHTML = legenda + resumo.map(r => {
      const faixa = (d.faixas || {})[r.provedor] || [];
      const barras = faixa.map(dia =>
        '<i data-s="' + dia.saude + '" title="' + dia.dia + ': ' + dia.ok + ' ok, ' +
        dia.err + ' erro' + (dia.motivo ? ': ' + dia.motivo : '') + '"></i>').join('');
      const alertas = [];
      if (r.dias_de_atencao) alertas.push(r.dias_de_atencao + ' instável');
      if (r.dias_ruins) alertas.push(r.dias_ruins + ' com falha');
      const nota = r.dias_com_uso + ' dias usados · ' +
        (alertas.length ? alertas.join(' · ') : 'todos saudáveis') +
        (r.pior_motivo ? ' · ' + r.pior_motivo : '');
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
}

async function atualizar() {
  try {
    const d = await (await fetch('painel/dados')).json();
    estado = d;
    desenharAgora();
    $('pulso').innerHTML = '<b>' + d.provedores.length + '</b> na cadeia<br>' +
      '<b>' + d.chamadas + '</b> chamadas';
    if (d.ferramentas) {
      // Redesenha porque a conexão pode mudar enquanto a tela está aberta.
      const escolhida = (document.querySelector('.aba[aria-pressed="true"]') || {}).dataset;
      ferramentas = d.ferramentas;
      const pedida = new URLSearchParams(window.location.search).get('ferramenta');
      desenharAbas((escolhida && escolhida.id) || pedida || (ferramentas[0] && ferramentas[0].id));
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
    $('trazer-ambiente').hidden = !(d.credenciais || []).some(c => c.origem === 'ambiente');
  } catch (e) { $('credenciais').textContent = 'não consegui ler as contas'; return; }

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
        (c.paga ? ' <small>paga</small>' : '') + '</span><code>' + c.id + '</code>' +
        '<span class="mover">' +
        '<button type="button" data-ref-move="-1" data-indice="' + i +
        '" aria-label="Subir ' + c.label + '"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" data-ref-move="1" data-indice="' + i +
        '" aria-label="Descer ' + c.label + '"' + (i === ordem.length - 1 ? ' disabled' : '') + '>↓</button>' +
        '<button type="button" class="apagar" data-ref-remove="' + i +
        '" aria-label="Remover ' + c.label + '">×</button></span></li>';
    }).join('') + '</ol>' : '<p class="vazio compacto">Nenhuma conta escolhida.</p>') +
    (fora.length ? '<div class="adicionar-ref"><select id="ref-conta">' +
      fora.map(c => '<option value="' + c.id + '">' + c.label +
        (c.paga ? ' · paga' : '') + '</option>').join('') + '</select>' +
      '<button type="button" class="acao" id="ref-adicionar">adicionar</button></div>' : '') +
    '<p class="como">' + T('cred.ref_header') +
    ' <code>X-RobinBandit-Mode: reinforced</code>.</p></div>';

  const salvarOrdem = async nova => {
    const r = await fetch('contas/reforcado', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contas: nova }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'não deu');
    contas.reforcado = (await r.json()).contas;
    desenharReservados();
    recado('recado-prov', 'Nova ordem aplicada na próxima chamada.');
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
    '<button class="aba" type="button" data-cred="false" aria-pressed="' + !contasDeTodos + '">Configuradas</button>' +
    '<button class="aba" type="button" data-cred="true" aria-pressed="' + contasDeTodos + '">Todas</button>';
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
      ? 'Nenhuma conta no catálogo.'
      : 'Nenhuma conta configurada ainda. Veja todas acima e cole uma chave.') + '</p>';
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
          (c.configurada ? 'autenticado' : 'não conectado') + '</span></div>' +
          '<p class="cli">Quem autentica é o <b>' + qual + '</b>, com a assinatura que você já usa. ' +
          'O RobinBandit não lê nem renova credencial. Ele só chama o executável.' +
          // Mostra detalhe só quando ele acrescenta informação.
          (c.detalhe && c.detalhe !== 'autenticado' ? ' <em>' + c.detalhe + '</em>' : '') +
          (c.configurada ? '' : ' Rode <code>' + comando + '</code> no terminal e recarregue.') +
          '</p></div>';
      }
      // A marca de paga é da chave, não da variável inteira.
      const chaves = (c.chaves || []).map(k =>
        '<span class="chave' + (k.paga ? ' e-paga' : '') + '">' +
        '<b' + (k.nome ? '' : ' class="anonima"') + '>' + (k.nome || 'sem nome') + '</b>' +
        '<span class="dica">' + k.dica + '</span>' +
        '<button type="button" class="marca-paga' + (k.paga ? '' : ' off') + '" data-paga="' +
        c.key_env + '" data-i="' + k.i + '" data-vale="' + (k.paga ? '1' : '0') +
        '" title="' + (k.paga ? 'crédito pago; clique para desmarcar' : 'marcar como crédito pago') +
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
        // O valor nunca volta para a tela.
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
  // Compacta números grandes para leitura rápida.
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.', ',') + ' bi';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', ',') + ' mi';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace('.', ',') + ' mil';
  return String(n);
}

function dolar(n) {
  return new Intl.NumberFormat(IDIOMA === 'pt' ? 'pt-BR' : 'en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2,
    maximumFractionDigits: Number(n || 0) < 0.01 ? 4 : 2
  }).format(Number(n || 0));
}

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const SEMANA = ['', 'seg', '', 'qua', '', 'sex', ''];

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
      ? milhar(x.total) + ' tokens em ' + x.chamadas + ' chamada' + (x.chamadas === 1 ? '' : 's')
      : 'sem uso';
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
  desenharPeriodosUso();
  try { d = await (await fetch('uso?dias=' + periodoUso)).json(); }
  catch (e) { $('uso-calendario').textContent = 'não consegui ler o uso'; return; }

  const mes = d.periodo || d.total || {};
  const tudo = d.periodo || d.total || {};
  const dias = d.calendario || [];
  const gastou = (tudo.total || 0) > 0;

  // Sem dados, mostra explicação em vez de métricas zeradas.
  const comCusto = mes.chamadas_com_custo || 0;
  $('uso-numeros').innerHTML = gastou
    ? '<div><b class="verde">' + milhar(mes.entrada || 0) + '</b><span>entrada</span>' +
      '<small>tokens nos últimos ' + periodoUso + ' dias</small></div>' +
      '<div><b>' + milhar(mes.saida || 0) + '</b><span>saída</span>' +
      '<small>' + (mes.cacheado ? milhar(mes.cacheado) + ' tokens vieram do cache' : 'tokens nos últimos ' + periodoUso + ' dias') + '</small></div>' +
      '<div><b class="ambar">' + (comCusto ? dolar(mes.custo_usd) : 'não informado') + '</b><span>custo em USD</span>' +
      '<small>' + (comCusto ? 'informado em ' + comCusto + ' de ' + mes.chamadas + ' chamadas' : 'nenhum provedor enviou preço') + '</small></div>' +
      '<div><b>' + (mes.chamadas || 0) + '</b><span>chamadas</span>' +
      '<small>' + milhar(mes.total || 0) + ' tokens no total</small></div>'
    : '';

  $('uso-tendencia').innerHTML = gastou ? graficoTendencia(dias) : '';
  $('uso-periodo-titulo').textContent = periodoUso === 365 ? 'Seu ano' : 'Dias do período';

  $('uso-calendario').innerHTML = gastou
    ? calendarioDe(dias)
    : '<div class="sem-uso"><b>Nenhum turno medido ainda</b><span>' +
      'A contagem começa na primeira resposta que passar por aqui. Aponte sua ' +
      'ferramenta para este endereço na tela Conectar. Só entra no gráfico quem ' +
      'informa o consumo junto da resposta.</span></div>';

  const linhas = d.por_provedor || [];
  const maior = Math.max(1, ...linhas.map(x => x.total));
  $('uso-detalhe').hidden = !linhas.length;
  $('uso-provedores').innerHTML = linhas.map(x =>
    '<div class="gasto">' + logo(x.provedor) +
    '<span class="quem">' + x.provedor + '</span>' +
    '<span class="barra"><span style="width:' + Math.round(x.total / maior * 100) + '%"></span></span>' +
    '<span class="detalhe">' + milhar(x.entrada) + ' entrada<br>' + milhar(x.saida) + ' saída</span>' +
    '<span class="n">' + milhar(x.total) + '<small>' +
      (x.chamadas_com_custo ? dolar(x.custo_usd) : 'custo não informado') +
    '</small></span></div>').join('');
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
    // Acima de 80%, destaca proximidade do limite.
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
    'próximo turno. O ping é uma chamada mínima, fora de um turno, só para saber. ' +
    'Custa uma chamada e por isso vem desligado.</p>' +
    '<div class="campos">' +
    '<label>a cada <input type="number" id="ping-intervalo" min="60" step="30" value="' +
    Math.round(p.intervalo_s || 300) + '"> segundos</label>' +
    '<label><input type="checkbox" id="ping-cooldown"' + (p.so_em_cooldown ? ' checked' : '') +
    '> apenas provedores em cooldown</label>' +
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
  const rotulos = { 7: '7 dias', 30: '30 dias', 90: '90 dias', 365: '1 ano' };
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
  return '<div class="tendencia-topo"><span>Tokens por dia</span><b>pico de ' +
    milhar(melhor.total || 0) + ' em ' + melhor.dia + '</b></div>' +
    '<svg viewBox="0 0 ' + largura + ' ' + altura + '" role="img" aria-label="Tendência de tokens no período">' +
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
    recado('conexao', 'Não consegui copiar. Selecione o bloco e copie manualmente.');
  }
});

trocarTela(new URLSearchParams(window.location.search).get('tela') || 'agora');

carregarConfig().catch(() => recado('recado-prov', 'não consegui ler a configuração'));
carregarCredito();
carregarCredenciais();
carregarJanelas();
carregarUso();
carregarHistorico();
atualizar();
setInterval(atualizar, 4000);
