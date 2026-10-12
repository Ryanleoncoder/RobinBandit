const RBClassificador = (() => {
  let dados = null, filas = {}, salvas = {}, provedores = [], escolhido = null;
  let classificador = {tipo:'nenhum',provedor:'',modelo:''}, classificadorSalvo = null;
  let contextos = {}, contextosSalvos = {};
  let rascunhoAlvo={provedor:'',modelo:''}, contextosAbertos=new Set();
  let arrasto = null, ocupado = false, ativo = '', alvoAtivo = -1, falhou = -1, timers = [];
  let apresentando = false, idleTimer = null, olharTimer = null, piscadas = [];
  const movimentoReduzido = matchMedia('(prefers-reduced-motion: reduce)');
  const copia = valor => JSON.parse(JSON.stringify(valor));
  const igual = (a, b) => a.provedor === b.provedor && a.modelo === b.modelo;
  const el = (tag, classe, texto) => { const n = document.createElement(tag); n.className = classe || ''; if (texto != null) n.textContent = texto; return n; };
  const nomeProvedor = nome => provedores.find(p => p.nome === nome)?.label || nome;
  const mudou = () => JSON.stringify(filas) !== JSON.stringify(salvas) || JSON.stringify(classificador) !== JSON.stringify(classificadorSalvo) || JSON.stringify(contextos) !== JSON.stringify(contextosSalvos);
  const recado = texto => { $('clf-status').textContent = texto; };

  function controles() {
    const incompleto=classificador.tipo==='llm' && (!classificador.provedor || !classificador.modelo.trim());
    $('clf-salvar').disabled = ocupado || !dados || !mudou() || incompleto;
    $('clf-descartar').disabled = ocupado || !mudou();
    $('clf-exemplo').disabled = ocupado || !dados;
    $('clf-tipo').disabled = ocupado || !dados;
    $('clf-provedor').disabled = ocupado || !dados;
    $('clf-modelo').disabled = ocupado || !dados || !rascunhoAlvo.provedor;
    $('clf-add-modelo').disabled=ocupado || !dados || !rascunhoAlvo.provedor || !rascunhoAlvo.modelo.trim();
    $('clf-testar').disabled = ocupado || !dados || classificador.tipo!=='llm' || incompleto || !$('clf-teste-pedido').value.trim();
    $('clf-teste-pedido').disabled=$('clf-teste-contexto').disabled=ocupado;
    $('clf-rosto').disabled=ocupado;
    $('clf-gerir').querySelectorAll('button').forEach(b=>{b.disabled=ocupado || b.dataset.limite==='true';});
    $('clf-caixas').querySelectorAll('textarea').forEach(campo=>{campo.disabled=ocupado || !dados;});
    if(dados && $('modo-rota')?.value==='classifier')$('clf-ativacao').textContent=classificador.tipo==='llm' && classificador.modelo && Object.values(filas).some(f=>f.length)
      ? L('Classificador selecionado. Salve as alterações para usá-las nas próximas chamadas.','Classifier selected. Save changes to apply them to subsequent requests.')
      : L('Configuração incompleta: escolha o classificador e adicione modelos aos blocos. O teste avalia só o classificador.','Incomplete configuration: choose the classifier and add box models. Testing evaluates only the classifier.');
  }
  function modelosDoClassificador() {
    return provedores.find(p=>p.nome===rascunhoAlvo.provedor)?.modelos || [];
  }
  function alvosClassificador() {
    if(classificador.tipo!=='llm' || !classificador.provedor || !classificador.modelo.trim())return [];
    return [{provedor:classificador.provedor,modelo:classificador.modelo.trim()},...(classificador.reservas || [])];
  }
  function definirClassificadores(alvos) {
    classificador=alvos.length ? {tipo:'llm',...alvos[0]} : {tipo:'nenhum',provedor:'',modelo:''};
    if(alvos.length>1)classificador.reservas=copia(alvos.slice(1));
  }
  function adicionarClassificador(alvo, mostrar=true) {
    const alvos=alvosClassificador();
    if(alvos.some(a=>igual(a,alvo)))return;
    if(alvos.length>=6){recado(L('O classificador aceita até seis modelos.', 'The classifier accepts up to six models.'));return;}
    alterar(()=>definirClassificadores([...alvos,copia(alvo)]));desenharClassificador();if(mostrar)abrirGerir(true);piscar();
  }
  function abrirGerir(aberto) {
    if(aberto && $('clf-gerir').parentElement!==document.body)document.body.append($('clf-gerir'));
    $('clf-gerir').hidden=!aberto;$('clf-rosto').setAttribute('aria-expanded',String(aberto));
    posicionarGerir();
  }
  function posicionarGerir() {
    const caixa=$('clf-gerir');if(caixa.hidden)return;
    const rosto=$('clf-rosto').getBoundingClientRect(), r=caixa.getBoundingClientRect();
    const x=Math.max(12,Math.min(innerWidth-r.width-12,rosto.x+rosto.width/2-r.width/2));
    const abaixo=rosto.bottom+12;
    const y=abaixo+r.height<=innerHeight-12 ? abaixo : Math.max(12,rosto.top-r.height-12);
    caixa.style.left=x+'px';caixa.style.top=y+'px';
  }
  function desenharClassificadores() {
    const alvos=alvosClassificador();
    for(const id of ['clf-lista-classificadores','clf-lista-config']){
    const onde=$(id);onde.replaceChildren();
    if(!alvos.length)onde.append(el('p','dica',L('Arraste um modelo para o rosto ou escolha por provedor e ID.', 'Drop a model onto the face or choose by provider and ID.')));
    alvos.forEach((alvo,i)=>{
      const linha=el('div','clf-classificador-item');linha.append(el('span','',(i+1)+'. '+alvo.modelo+' · '+nomeProvedor(alvo.provedor)));
      for(const [passo,simbolo,rotulo] of [[-1,'↑',L('Mover antes: ','Move earlier: ')],[1,'↓',L('Mover depois: ','Move later: ')],[0,'×',L('Remover classificador: ','Remove classifier: ')]]){
        const b=el('button','',simbolo);b.type='button';b.setAttribute('aria-label',rotulo+alvo.modelo);
        b.dataset.limite=String((passo===-1 && i===0) || (passo===1 && i===alvos.length-1));b.disabled=ocupado || b.dataset.limite==='true';
        b.addEventListener('click',()=>{
          alterar(()=>{if(!passo)alvos.splice(i,1);else [alvos[i],alvos[i+passo]]=[alvos[i+passo],alvos[i]];definirClassificadores(alvos);});desenharClassificador();
        });linha.append(b);
      }
      onde.append(linha);
    });
    }
    posicionarGerir();
  }
  function avisoDoClassificador() {
    const llm=classificador.tipo==='llm', fora=rascunhoAlvo.modelo.trim() && !modelosDoClassificador().includes(rascunhoAlvo.modelo.trim());
    $('clf-modelo-aviso').hidden=!llm;
    $('clf-modelo-aviso').textContent=fora
      ? L('ID fora do catálogo, não verificado. Salvar não consulta o provedor.', 'ID outside the catalog, not verified. Saving does not query the provider.')
      : L('Escolha um provedor e um modelo. As credenciais são as já cadastradas no RB; não são copiadas para esta configuração.', 'Choose a provider and model. Credentials remain in RB account settings and are not copied into this configuration.');
  }
  function desenharClassificador() {
    $('clf-contrato-texto').textContent=dados?.contrato?.instrucao || '';
    $('clf-tipo').value=classificador.tipo;
    $('clf-adicionar-llm').hidden=classificador.tipo!=='llm';
    $('clf-especializado-aviso').hidden=classificador.tipo==='llm';
    const select=$('clf-provedor');select.replaceChildren();
    const vazio=el('option','',L('Escolha um provedor','Choose a provider'));vazio.value='';select.append(vazio);
    provedores.filter(p=>!p.conta_de && !p.e_aviso).forEach(p=>{
      const o=el('option','',p.label+(p.configurada?'':L(' (sem conexão)',' (not connected)')));o.value=p.nome;select.append(o);
    });
    select.value=rascunhoAlvo.provedor;
    $('clf-modelo').value=rascunhoAlvo.modelo;
    const lista=$('clf-modelos');lista.replaceChildren();
    [...new Set(modelosDoClassificador())].forEach(modelo=>{const o=el('option');o.value=modelo;lista.append(o);});
    avisoDoClassificador();controles();
    desenharClassificadores();
    $('clf-centro-estado').textContent=classificador.tipo==='llm' && classificador.modelo ? classificador.modelo : L('Não escolhido','Not selected');
    $('clf-resumo').textContent=alvosClassificador().length ? alvosClassificador().length+L(' classificadores',' classifiers') : L('Especializado não conectado','Specialized classifier not connected');
  }
  function parar(aviso = false, manterOlhar = false) {
    timers.forEach(clearTimeout); timers = [];
    clearTimeout(olharTimer);olharTimer=null;
    ativo = ''; alvoAtivo = falhou = -1;
    if(!manterOlhar)olhar(0,0);
    $('clf-centro-estado').textContent = classificador.tipo==='llm' && classificador.modelo ? classificador.modelo : L('Não escolhido', 'Not selected');
    if (dados) desenharCaixas();
    apresentando = false; agendarPiscadaIdle();
  }
  function piscar() {
    piscadas.forEach(a=>a.cancel());piscadas=[];
    if(movimentoReduzido.matches)return;
    piscadas=Array.from($('clf-mapa').querySelectorAll('.clf-olho'),o=>o.animate(
      [{transform:'scaleY(1)'},{transform:'scaleY(.08)',offset:.5},{transform:'scaleY(1)'}],{duration:230}));
  }
  function agendarPiscadaIdle() {
    const visivel=()=>dados && !document.hidden && $('classificador-painel').offsetWidth>0 && !movimentoReduzido.matches;
    if(!visivel()){clearTimeout(idleTimer);idleTimer=null;clearTimeout(olharTimer);olharTimer=null;piscadas.forEach(a=>a.cancel());return;}
    if(idleTimer!==null)return;
    idleTimer=setTimeout(()=>{
      idleTimer=null;if(!visivel())return;
      if(!apresentando && Math.random()<.4){
        const nivel=ativo, base=direcaoEscolhida();
        const angulo=Math.random()*Math.PI*2;
        const x=nivel ? base.x+Math.round((Math.random()-.5)*4) : Math.round(Math.cos(angulo)*10);
        const y=nivel ? base.y+Math.round((Math.random()-.5)*4) : Math.round(Math.sin(angulo)*12);
        olhar(x,y);
        olharTimer=setTimeout(()=>{olharTimer=null;if(visivel() && !apresentando && ativo===nivel)olhar(base.x,base.y);},1300+Math.random()*700);
      }
      piscar();agendarPiscadaIdle();
    },4500+Math.random()*2500);
  }
  function olhar(x,y) {
    const olhos=$('clf-mapa').querySelector('.clf-olhos');
    if(olhos.style.getPropertyValue('--olhar-x')===x+'px' && olhos.style.getPropertyValue('--olhar-y')===y+'px')return;
    olhos.getAnimations({subtree:true}).forEach(a=>a.cancel());
    olhos.style.setProperty('--olhar-x',x+'px');olhos.style.setProperty('--olhar-y',y+'px');
  }
  function direcaoEscolhida() {
    const mapa = $('clf-mapa'), centro = mapa.querySelector('.clf-olhos');
    const caixa=mapa.querySelector('[data-caixa="'+ativo+'"]');
    if (!mapa.offsetWidth || !centro || !caixa) return {x:0,y:0};
    const c = centro.getBoundingClientRect();
    const cx = c.x + c.width / 2, cy = c.y + c.height / 2;
    const r=caixa.getBoundingClientRect();
    return {x:Math.sign(r.x+r.width/2-cx)*10,y:Math.sign(r.y+r.height/2-cy)*12};
  }
  function atualizarOlhar() {
    if(!ativo)return;
    const direcao=direcaoEscolhida();olhar(direcao.x,direcao.y);
  }
  function alterar(mutacao) {
    if (ocupado) return;
    parar(); mutacao(); desenharCaixas(); controles();
    recado(L('Alterações não salvas. A rota atual não mudou.', 'Unsaved changes. Current routing is unchanged.'));
  }
  function inserir(alvo, nivel, indice, origem = '') {
    if (!dados || !Object.hasOwn(filas, nivel)) return;
    alterar(() => {
      const destino = filas[nivel], anterior = destino.findIndex(a => igual(a, alvo));
      if (anterior >= 0) { destino.splice(anterior,1); if (anterior < indice) indice--; }
      if (origem && origem !== nivel) filas[origem] = filas[origem].filter(a => !igual(a,alvo));
      destino.splice(Math.max(0,Math.min(indice,destino.length)),0,copia(alvo));
    });
  }
  function chip(alvo, origem = '', indice = -1) {
    const item = el('div','clf-modelo'+(origem?' na-fila':'')); item.draggable = true;
    const b = el('button','clf-modelo-nome'); b.type = 'button'; b.draggable = true;
    const img = el('span','clf-logo'); img.innerHTML = logo(alvo.provedor); b.append(img);
    const texto = el('span','clf-modelo-texto'); texto.append(el('strong','',(origem ? (indice+1)+'. ' : '')+alvo.modelo),el('small','',nomeProvedor(alvo.provedor))); b.append(texto); item.append(b);
    b.addEventListener('click', () => {
      escolhido = copia(alvo); $('clf-modelo-escolhido').textContent = alvo.modelo + ' · ' + nomeProvedor(alvo.provedor);
      $('clf-escolha').hidden = false; $('clf-destino').focus();
    });
    item.addEventListener('dragstart', e => {
      if (ocupado) {e.preventDefault();return;}
      arrasto = {alvo:copia(alvo),origem}; e.dataTransfer.setData('text/plain',JSON.stringify(alvo)); e.dataTransfer.effectAllowed = origem ? 'move' : 'copy';
    });
    item.addEventListener('dragend', () => { arrasto = null; document.querySelectorAll('.clf-caixa.alvo').forEach(c=>c.classList.remove('alvo')); });
    if (origem) {
      item.dataset.pos = indice;
      const opcoes=el('button','clf-opcoes','⋯');opcoes.type='button';opcoes.setAttribute('aria-label',L('Opções de ', 'Options for ')+alvo.modelo);opcoes.setAttribute('aria-expanded','false');
      item.append(opcoes);
      const acoes = el('span','clf-modelo-acoes');acoes.hidden=true;
      opcoes.addEventListener('click',()=>{acoes.hidden=!acoes.hidden;opcoes.setAttribute('aria-expanded',String(!acoes.hidden));item.classList.toggle('acoes-abertas',!acoes.hidden);});
      for (const [passo, simbolo, rotulo] of [[-1,'←',L('Mover antes: ', 'Move earlier: ')],[1,'→',L('Mover depois: ', 'Move later: ')],[0,'×',L('Remover da caixa: ', 'Remove from box: ')]]) {
        const btn = el('button','',simbolo); btn.type='button'; btn.setAttribute('aria-label',rotulo+alvo.modelo);
        btn.disabled = ocupado || (passo === -1 && indice === 0) || (passo === 1 && indice === filas[origem].length-1);
        btn.addEventListener('click', () => alterar(() => {
          if (!passo) filas[origem].splice(indice,1);
          else [filas[origem][indice],filas[origem][indice+passo]] = [filas[origem][indice+passo],filas[origem][indice]];
        })); acoes.append(btn);
      }
      item.append(acoes);
      item.classList.toggle('tentando',origem===ativo && indice===alvoAtivo);
      item.classList.toggle('falhou',origem===ativo && indice===falhou);
    }
    return item;
  }
  function desenharCaixas() {
    const onde = $('clf-caixas'); onde.replaceChildren();
    dados.niveis.forEach(nivel => {
      const caixa = el('section','clf-caixa'); caixa.dataset.caixa = nivel.id;
      caixa.classList.toggle('escolhida',nivel.id===ativo);
      const quantidade=filas[nivel.id].length;
      const titulo = el('header',''); titulo.append(el('strong','',nivel[IDIOMA] || nivel.pt),el('small','',quantidade+(quantidade===1?L(' modelo',' model'):L(' modelos',' models')))); caixa.append(titulo);
      const lista = el('div','clf-fila');
      filas[nivel.id].forEach((alvo,i) => lista.append(chip(alvo,nivel.id,i)));
      if (!filas[nivel.id].length) lista.append(el('p','dica',L('Arraste um modelo para cá', 'Drop a model here')));
      caixa.append(lista);
      const detalhe=el('details','clf-contexto-detalhe');detalhe.open=contextosAbertos.has(nivel.id);
      const resumo=el('summary','',L('Contexto do bloco','Box context')+(contextos[nivel.id]?L(' · definido',' · set'):L(' · opcional',' · optional')));detalhe.append(resumo);
      detalhe.addEventListener('toggle',()=>{
        if(detalhe.open){contextosAbertos.add(nivel.id);detalhe.classList.toggle('para-cima',detalhe.getBoundingClientRect().bottom+200>innerHeight-12);}
        else contextosAbertos.delete(nivel.id);
      });
      const rotulo=el('label','clf-contexto',L('Contexto deste bloco','Context for this box'));
      const campo=el('textarea');campo.id='clf-contexto-'+nivel.id;campo.maxLength=2000;campo.rows=2;
      campo.value=contextos[nivel.id] || '';campo.disabled=ocupado;
      campo.placeholder=L('Opcional: quando você prefere os modelos daqui', 'Optional: when you prefer these models');
      rotulo.htmlFor=campo.id;rotulo.append(campo);detalhe.append(rotulo);caixa.append(detalhe);
      campo.addEventListener('focus',()=>{
        if(!apresentando)return;
        parar(true);$('clf-contexto-'+nivel.id).focus();
      });
      campo.addEventListener('input',()=>{
        contextos[nivel.id]=campo.value;controles();
        recado(L('Contexto não salvo. Nenhuma classificação foi executada.', 'Unsaved context. No classification was run.'));
      });
      caixa.addEventListener('dragover', e => { if (!arrasto || ocupado) return; e.preventDefault(); caixa.classList.add('alvo'); });
      caixa.addEventListener('dragleave', e => {if(!caixa.contains(e.relatedTarget))caixa.classList.remove('alvo');});
      caixa.addEventListener('drop', e => {
        e.preventDefault(); caixa.classList.remove('alvo'); if(!arrasto || ocupado)return;
        const item = e.target.closest('[data-pos]');
        let indice = filas[nivel.id].length;
        if(item)indice=Number(item.dataset.pos)+(e.clientX > item.getBoundingClientRect().x+item.getBoundingClientRect().width/2 ? 1:0);
        const mover=arrasto; arrasto=null; inserir(mover.alvo,nivel.id,indice,mover.origem);
      }); onde.append(caixa);
    });
    atualizarOlhar();
  }
  function desenharCatalogo() {
    const termo = normalizarBusca($('clf-busca').value), onde = $('clf-catalogo'); onde.replaceChildren();
    let total = 0;
    provedores.filter(p => !p.conta_de && !p.e_aviso).forEach(p => {
      [...new Set(p.modelos || [])].forEach(modelo => {
        if(!normalizarBusca(p.nome+' '+p.label+' '+modelo).includes(termo))return;
        onde.append(chip({provedor:p.nome,modelo})); total++;
      });
    });
    if (!total) onde.append(el('p','dica',L('Nenhum modelo neste filtro. Adicione modelos na aba Modelos.', 'No matching model. Add models in the Models tab.')));
    $('clf-catalogo-contagem').textContent=total+L(' modelos',' models');
  }
  async function carregar(configuracao) {
    provedores = configuracao.provedores || [];
    if (dados) {traduzirNiveis();desenharClassificador();desenharCaixas();desenharCatalogo();return;}
    try {
      const r = await fetch('config/classificacao');
      const d = await r.json(); if(!r.ok)throw new Error(d.detail || L('Falha ao ler caixas','Could not load boxes'));
      dados = d; filas = copia(d.filas); salvas = copia(filas);
      classificador=copia(d.classificador || {tipo:'nenhum',provedor:'',modelo:''});classificadorSalvo=copia(classificador);
      contextos=copia(d.contextos || Object.fromEntries(d.niveis.map(n=>[n.id,''])));contextosSalvos=copia(contextos);
      traduzirNiveis();
      desenharClassificador(); desenharCaixas(); desenharCatalogo(); controles(); agendarPiscadaIdle();
      vista(configuracao.estrategia==='classifier');
      recado(L('Pronto para testar. O teste não executa os modelos dos blocos.', 'Ready to test. Testing does not run box models.'));
    } catch(e){recado(e.message);}
  }
  function traduzirNiveis() {
    const destino=$('clf-destino'), selecionado=destino.value;destino.replaceChildren();
    dados.niveis.forEach(n=>{const o=el('option','',n[IDIOMA]||n.pt);o.value=n.id;destino.append(o);});
    const o=el('option','',L('Classificador (rostinho)','Classifier (face)'));o.value='classificador';destino.append(o);
    if(Array.from(destino.options).some(o=>o.value===selecionado))destino.value=selecionado;
  }
  function vista(aberta) {
    $('clf-workspace').hidden=!aberta;$('rota-atual').hidden=aberta;
    if(!aberta){parar();abrirGerir(false);}
    const url=new URL(location.href);if(aberta)url.searchParams.set('classificador','1');else url.searchParams.delete('classificador');history.replaceState({},'',url);
    if(aberta)atualizarOlhar();agendarPiscadaIdle();
    const modo=$('modo-rota')?.value || 'adaptive';
    $('clf-ativacao').textContent=modo==='classifier' ? L('Classificador ativo na rota normal.','Classifier active for normal routing.')
      : L('Configuração e teste apenas. Rota ativa: ','Settings and testing only. Active routing: ')+T('prov.modo.'+modo)+'.';
    controles();
  }
  function navegar(tela) {if(tela!=='provedores'){parar();abrirGerir(false);}else if(dados)atualizarOlhar();agendarPiscadaIdle();}
  function iniciar() {
    $('clf-rosto').addEventListener('click',()=>{piscar();abrirGerir($('clf-gerir').hidden);});
    $('clf-fechar-gerir').addEventListener('click',()=>{abrirGerir(false);$('clf-rosto').focus();});
    $('clf-editar-llm').addEventListener('click',()=>{abrirGerir(false);$('clf-config').open=true;$('clf-tipo').focus();});
    document.addEventListener('click',e=>{if(!$('clf-gerir').hidden && !e.composedPath().includes($('clf-gerir')) && !e.composedPath().includes($('clf-rosto')))abrirGerir(false);});
    document.addEventListener('keydown',e=>{if(e.key==='Escape' && !$('clf-gerir').hidden){abrirGerir(false);$('clf-rosto').focus();}});
    document.addEventListener('scroll',posicionarGerir,{capture:true,passive:true});
    window.addEventListener('resize',posicionarGerir);
    $('clf-rosto').addEventListener('dragover',e=>{if(!arrasto || ocupado)return;e.preventDefault();e.dataTransfer.dropEffect='copy';$('clf-rosto').classList.add('alvo');});
    $('clf-rosto').addEventListener('dragleave',()=>{$('clf-rosto').classList.remove('alvo');});
    $('clf-rosto').addEventListener('drop',e=>{e.preventDefault();$('clf-rosto').classList.remove('alvo');if(!arrasto || ocupado)return;const alvo=arrasto.alvo;arrasto=null;adicionarClassificador(alvo);});
    $('clf-teste-pedido').addEventListener('input',controles);
    $('clf-teste').addEventListener('submit',async e=>{
      e.preventDefault();if($('clf-testar').disabled)return;
      parar(false,true);ocupado=true;controles();
      abrirGerir(false);
      const mapa=$('clf-mapa').getBoundingClientRect();
      if(mapa.bottom>innerHeight || mapa.top<0)$('clf-mapa').scrollIntoView({block:'center',behavior:movimentoReduzido.matches?'instant':'smooth'});
      $('clf-centro-estado').textContent=L('Classificando…','Classifying…');recado(L('Teste real: enviando o pedido à LLM classificadora.', 'Live test: sending the request to the classifier LLM.'));
      try{
        const r=await fetch('config/classificacao/testar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pedido:$('clf-teste-pedido').value,contexto:$('clf-teste-contexto').value,classificador,contextos})});
        const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:L('Não foi possível classificar.','Could not classify.'));
        ativo=d.nivel;alvoAtivo=falhou=-1;
        $('clf-centro-estado').textContent=dados.niveis.find(n=>n.id===d.nivel)?.[IDIOMA] || d.nivel;
        recado(L('Classificação: ','Classification: ')+d.nivel+' · '+d.modelo+' · '+(d.duracao_ms/1000).toFixed(1)+' s'+(d.uso?' · '+usoCurto(d.uso):'')+L('. Nenhum modelo da caixa foi chamado.', '. No box model was called.'));
        desenharCaixas();piscar();
      }catch(err){$('clf-centro-estado').textContent=L('Teste falhou','Test failed');recado(err.message);}
      finally{ocupado=false;controles();agendarPiscadaIdle();carregarUso();}
    });
    $('clf-tipo').addEventListener('change',()=>{alterar(()=>{classificador.tipo=$('clf-tipo').value;});desenharClassificador();});
    $('clf-provedor').addEventListener('change',()=>{
      rascunhoAlvo={provedor:$('clf-provedor').value,modelo:''};desenharClassificador();
    });
    $('clf-modelo').addEventListener('input',()=>{
      rascunhoAlvo.modelo=$('clf-modelo').value;avisoDoClassificador();controles();
    });
    $('clf-add-modelo').addEventListener('click',()=>{adicionarClassificador({provedor:rascunhoAlvo.provedor,modelo:rascunhoAlvo.modelo.trim()},false);rascunhoAlvo.modelo='';desenharClassificador();});
    $('clf-exemplo').addEventListener('click',()=>{
      if(!dados || ocupado)return;
      const disponiveis=provedores.filter(p=>!p.conta_de && !p.e_aviso && p.configurada && p.modelos?.length);
      const fonte=disponiveis.length?disponiveis:provedores.filter(p=>!p.conta_de && !p.e_aviso && p.modelos?.length);
      const candidatos=fonte.flatMap(p=>p.modelos.map(modelo=>({provedor:p.nome,modelo})));
      if(!candidatos.length){recado(L('Não há modelos no catálogo para montar o exemplo.', 'No catalog models to build the example.'));return;}
      alterar(()=>dados.niveis.forEach((n,i)=>{if(!filas[n.id].length)filas[n.id]=copia(candidatos.slice(i%candidatos.length,i%candidatos.length+2));}));
      recado(L('Exemplo montado com modelos do catálogo. Não salvo e sem chamadas reais.', 'Example built with catalog models. Unsaved, with no real requests.'));
    });
    $('clf-catalogo-painel').addEventListener('toggle',agendarPiscadaIdle);
    $('clf-busca').addEventListener('input',desenharCatalogo);
    $('clf-cancelar-escolha').addEventListener('click',()=>{$('clf-escolha').hidden=true;escolhido=null;});
    $('clf-escolha').addEventListener('submit',e=>{e.preventDefault();if(!escolhido)return;const n=$('clf-destino').value;if(n==='classificador')adicionarClassificador(escolhido);else inserir(escolhido,n,filas[n].length);$('clf-escolha').hidden=true;escolhido=null;});
    $('clf-descartar').addEventListener('click',()=>{parar();filas=copia(salvas);classificador=copia(classificadorSalvo);contextos=copia(contextosSalvos);desenharClassificador();desenharCaixas();controles();recado(L('Alterações descartadas.','Changes discarded.'));});
    $('clf-salvar').addEventListener('click',async()=>{
      if(ocupado)return;parar();ocupado=true;controles();
      try{const d=await salvar('config/classificacao',{filas,classificador,contextos});filas=copia(d.filas);salvas=copia(filas);classificador=copia(d.classificador);classificadorSalvo=copia(classificador);contextos=copia(d.contextos);contextosSalvos=copia(contextos);recado(L('Configuração salva. O modo ativo não foi alterado.', 'Configuration saved. The active mode was not changed.'));}
      catch(e){recado(e.message);}finally{ocupado=false;desenharClassificador();desenharCaixas();controles();}
    });
    document.addEventListener('visibilitychange',()=>{if(document.hidden)parar(true);else agendarPiscadaIdle();});
    movimentoReduzido.addEventListener('change',()=>{piscadas.forEach(a=>a.cancel());clearTimeout(olharTimer);olharTimer=null;const d=direcaoEscolhida();olhar(d.x,d.y);agendarPiscadaIdle();});
    new ResizeObserver(atualizarOlhar).observe($('clf-mapa'));
    vista(false);
  }
  return {carregar,navegar,iniciar,vista};
})();
