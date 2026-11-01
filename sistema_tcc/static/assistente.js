'use strict';
/* Assistente guiado: jornada linear sobre a mesma API do painel avançado. */
const $ = id => document.getElementById(id);
const el = (tag, texto, cls) => { const n = document.createElement(tag); if (texto !== undefined) n.textContent = texto; if (cls) n.className = cls; return n; };
const fmt = v => Number.isFinite(v) ? new Intl.NumberFormat('pt-BR').format(v) : '—';
const pct = (v, c = 1) => Number.isFinite(v) ? (v * 100).toLocaleString('pt-BR', { minimumFractionDigits: c, maximumFractionDigits: c }) + '%' : '—';
const reduzido = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
const SVGNS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs) => { const n = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v)); return n; };

const CAPS = [
  { nome: 'Introdução', de: 0, ate: 5 }, { nome: 'Dados', de: 6, ate: 6 }, { nome: 'Agrupar', de: 7, ate: 7 },
  { nome: 'Treinar', de: 8, ate: 8 }, { nome: 'Resultados', de: 9, ate: 9 }, { nome: 'Consultar', de: 10, ate: 10 },
  { nome: 'Aprender', de: 11, ate: 11 },
];
const TOTAL = 12;
const ESSENCIAIS = 'HILKMFTWV';
const CORES = ['#137a6a', '#346db2', '#c27c0e', '#7b5ea7', '#aa4052', '#1f9e89', '#6b8e23', '#e0607e'];

let token = '', estado = null, execSel = null, atual = -1, trocaTimer = null;
let escolha = { fonte: 'todas', limite: 1000 };
let consultaId = null, mmseqsInfo = null, configInfo = null, fontesCarregadas = false;
let trilha = 'ec7', ec7 = null, ec7Busy = false;
const CLASSES_EC = [['EC 1', 'Oxidorredutase', 'reações de oxidação e redução'], ['EC 2', 'Transferase', 'transferem grupos químicos'], ['EC 3', 'Hidrolase', 'quebram ligações com água'], ['EC 4', 'Liase', 'quebram ligações sem água'], ['EC 5', 'Isomerase', 'rearranjam a molécula'], ['EC 6', 'Ligase', 'unem moléculas gastando energia'], ['EC 7', 'Translocase', 'movem íons ou moléculas por membranas']];

async function api(path, body) {
  const op = { cache: 'no-store' };
  if (body !== undefined) { op.method = 'POST'; op.headers = { 'Content-Type': 'application/json', 'X-TCC-Token': token }; op.body = JSON.stringify(body); }
  const r = await fetch(path, op); const d = await r.json();
  if (!r.ok || d.ok === false) throw new Error(d.erro || 'A solicitação falhou.');
  return d;
}

/* ---------- navegação ---------- */
const cenas = [...document.querySelectorAll('.cena')];

function montarTrilha() {
  const ol = $('trilha'); ol.replaceChildren();
  CAPS.forEach((c, i) => {
    const li = el('li'); const b = el('button'); b.type = 'button';
    b.append(el('b', String(i + 1)), el('span', c.nome));
    b.addEventListener('click', () => ir(c.de));
    li.append(b); ol.append(li);
  });
  const p = $('pontos'); p.replaceChildren();
  for (let i = 0; i < TOTAL; i++) p.append(el('i'));
}

function atualizarChrome(n) {
  document.body.classList.toggle('modo-intro', n <= 5);
  document.body.classList.toggle('modo-trab', n > 5);
  [...$('trilha').children].forEach((li, i) => {
    const c = CAPS[i];
    li.classList.toggle('atual', n >= c.de && n <= c.ate);
    li.classList.toggle('feito', n > c.ate);
    const b = li.firstChild; if (n >= c.de && n <= c.ate) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
  });
  [...$('pontos').children].forEach((d, i) => d.classList.toggle('at', i === n));
  $('barra-i').style.width = (n / (TOTAL - 1) * 100) + '%';
  $('voltar').disabled = n === 0;
  $('avancar').hidden = n === TOTAL - 1;
  $('avancar').textContent = n === 0 ? 'Começar →' : n === 8 ? 'Ver resultados →' : 'Próximo →';
  history.replaceState(null, '', '#p' + n);
}

function ir(n) {
  n = Math.max(0, Math.min(TOTAL - 1, n));
  if (n === atual) return;
  const dir = n >= atual ? 'frente' : 'tras';
  const velha = cenas[atual], nova = cenas[n];
  clearTimeout(trocaTimer);
  cenas.forEach(c => { if (c !== velha && c !== nova) { c.hidden = true; c.classList.remove('entra-frente', 'entra-tras', 'sai-frente', 'sai-tras'); } });
  if (velha) {
    velha.classList.remove('entra-frente', 'entra-tras'); velha.classList.add('sai-' + dir);
    trocaTimer = setTimeout(() => { velha.hidden = true; velha.classList.remove('sai-frente', 'sai-tras'); }, reduzido ? 0 : 240);
  }
  nova.classList.remove('sai-frente', 'sai-tras', 'entra-frente', 'entra-tras');
  nova.hidden = false; nova.scrollTop = 0; void nova.offsetWidth;
  if (atual >= 0) nova.classList.add('entra-' + dir); else nova.classList.add('entra-frente');
  atual = n;
  atualizarChrome(n);
  entrar(n);
}

function entrar(n) {
  if (n >= 6 && n <= 9) pollEc7();
  if (n === 6) { carregarDados(); renderTrilha(); }
  if (n === 7) { carregarMmseqs(); renderTrilha(); }
  if (n === 8) { renderTreino(); renderTrilha(); }
  if (n === 9) { renderResultados(); renderTrilha(); }
  if (n === 10) { renderLetras($('c-letras'), $('c-seq').value); }
  if (n === 11) montarAprender();
}

/* ---------- estado do sistema ---------- */
async function poll() {
  try {
    const s = await api('/api/estado' + (execSel ? '?execucao=' + encodeURIComponent(execSel) : ''));
    token = s.token; estado = s;
    $('conexao').textContent = 'Conectado ao seu PC'; $('conexao').classList.remove('off');
    aoEstado(s);
    if (atual >= 6 && atual <= 9) await pollEc7();
  } catch (e) { $('conexao').textContent = 'Sistema desconectado'; $('conexao').classList.add('off'); }
}
function aoEstado(s) {
  if (atual === 8 && trilha === 'gz') renderTreino();
  if (atual === 9 && trilha === 'gz') renderResultados(true);
  if (consultaId) acompanharConsulta(s);
}

/* ---------- cena 0: hélice ---------- */
function montarHelice() {
  const h = $('helice'); const N = 28;
  for (let i = 0; i < N; i++) {
    const x = (i + .5) / N * 100;
    for (const cls of ['a', 'b']) {
      const d = el('i', undefined, cls === 'b' ? 'b' : '');
      d.style.left = x + '%'; d.style.animationDelay = (-i * 0.13) + 's'; h.append(d);
    }
  }
}

/* ---------- cena 2: regra dos 9 aminoácidos ---------- */
function limparSeq(s) { return s.toUpperCase().replace(/[^A-Z]/g, ''); }
function renderLetras(box, texto) {
  box.replaceChildren();
  const s = limparSeq(texto).slice(0, 120);
  for (const ch of s) box.append(el('span', ch, ESSENCIAIS.includes(ch) ? 'ess' : ''));
}
function avaliarRegra(seq) {
  const s = limparSeq(seq); const tem = new Set(s);
  return { presentes: [...ESSENCIAIS].filter(a => tem.has(a)), ausentes: [...ESSENCIAIS].filter(a => !tem.has(a)), n: s.length };
}
function atualizarDemo() {
  const v = $('seq-demo').value; renderLetras($('demo-letras'), v);
  const r = avaliarRegra(v); const box = $('demo-ess'); box.replaceChildren();
  for (const a of ESSENCIAIS) box.append(el('span', a + (r.ausentes.includes(a) ? ' ✕' : ' ✓'), r.ausentes.includes(a) ? '' : 'ok'));
  const ver = $('demo-veredito');
  if (!r.n) { ver.textContent = 'Digite uma sequência'; ver.className = 'veredito'; return; }
  if (r.ausentes.length) { ver.textContent = 'Incompleta · faltam: ' + r.ausentes.join(', '); ver.className = 'veredito no'; }
  else { ver.textContent = 'Completa · os 9 aminoácidos essenciais estão presentes'; ver.className = 'veredito ok'; }
}

/* ---------- cena 3: demos ---------- */
const PONTOS = (() => {
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const centros = [[80, 62], [380, 62], [80, 198], [380, 198]]; const pts = [];
  centros.forEach(c => { for (let i = 0; i < 9; i++) { const a = rnd() * 6.283, r = 6 + rnd() * 24; pts.push([c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r]); } });
  return pts;
})();
function agrupar(limiar) {
  const pai = PONTOS.map((_, i) => i); const f = i => pai[i] === i ? i : (pai[i] = f(pai[i]));
  const D = 6 + (90 - limiar) / 60 * 100; const elos = [];
  for (let i = 0; i < PONTOS.length; i++) for (let j = i + 1; j < PONTOS.length; j++) {
    const d = Math.hypot(PONTOS[i][0] - PONTOS[j][0], PONTOS[i][1] - PONTOS[j][1]);
    if (d < D) { pai[f(i)] = f(j); elos.push([i, j]); }
  }
  const raizes = {}; PONTOS.forEach((_, i) => { const r = f(i); raizes[r] = (raizes[r] || 0) + 1; });
  const ordem = Object.keys(raizes).sort((a, b) => raizes[b] - raizes[a]); const cor = {}; ordem.forEach((r, i) => cor[r] = CORES[i % CORES.length]);
  return { elos, grupo: PONTOS.map((_, i) => f(i)), cor, n: ordem.length };
}
function demoCluster() {
  const svg = $('demo-cluster'); const v = Number($('id-slider').value); $('id-val').textContent = v + '%';
  const g = agrupar(v);
  let linhas = svg.querySelector('g.elos'); if (!linhas) { linhas = svgEl('g', { class: 'elos' }); svg.append(linhas); }
  linhas.replaceChildren();
  for (const [i, j] of g.elos) linhas.append(svgEl('line', { x1: PONTOS[i][0], y1: PONTOS[i][1], x2: PONTOS[j][0], y2: PONTOS[j][1], stroke: g.cor[g.grupo[i]] }));
  if (!svg.querySelector('circle')) PONTOS.forEach(p => svg.append(svgEl('circle', { cx: p[0], cy: p[1], r: 6.5 })));
  [...svg.querySelectorAll('circle')].forEach((c, i) => c.setAttribute('fill', g.cor[g.grupo[i]]));
  $('id-out').textContent = g.n + (g.n === 1 ? ' grupo' : ' grupos') + ' com ' + PONTOS.length + ' sequências. ' + (v === 50 ? 'O projeto usa 50%.' : 'O projeto usa 50% de identidade mínima.');
}
function demoBarras() {
  const b = $('demo-barras'); b.replaceChildren(); let x = 12345;
  for (let i = 0; i < 40; i++) { x = (x * 1103515245 + 12345) % 2147483648; const bar = el('i'); bar.style.height = (14 + (x % 86)) + '%'; bar.style.animationDelay = (i * 0.02) + 's'; b.append(bar); }
}
function demoRede() {
  const svg = $('demo-rede'); svg.replaceChildren();
  const camadas = [{ x: 70, n: 8, t: '320 entradas' }, { x: 230, n: 6, t: '64 neurônios' }, { x: 390, n: 2, t: 'classes' }];
  const pos = camadas.map(c => Array.from({ length: c.n }, (_, i) => [c.x, 40 + (i + .5) * (170 / c.n) + (8 - c.n) * 3]));
  for (let k = 0; k < 2; k++) for (const a of pos[k]) for (const b of pos[k + 1]) svg.append(svgEl('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }));
  pos.forEach(col => col.forEach(p => svg.append(svgEl('circle', { cx: p[0], cy: p[1], r: 8 }))));
  camadas.forEach(c => { const t = svgEl('text', { x: c.x, y: 242 }); t.textContent = c.t; svg.append(t); });
}
function montarAbas() {
  const abas = [...document.querySelectorAll('.aba')], paineis = [...document.querySelectorAll('.painel-aba')];
  abas.forEach(a => a.addEventListener('click', () => {
    const k = a.dataset.aba;
    abas.forEach(x => x.setAttribute('aria-selected', String(x === a)));
    paineis.forEach(p => { p.hidden = p.dataset.painel !== k; });
    if (k === '1') demoBarras();
  }));
}

/* ---------- trilha EC 1-7 (modelo principal) ---------- */
async function pollEc7() {
  if (ec7Busy) return; ec7Busy = true;
  try { ec7 = await api('/api/ec7'); renderEc7(); } catch (e) { /* sem estado EC7 */ } finally { ec7Busy = false; }
}
function definirTrilha(t) {
  trilha = t;
  document.querySelectorAll('#d-trilha .opc').forEach(o => o.setAttribute('aria-checked', String(o.dataset.trilha === t)));
  renderTrilha();
}
function renderTrilha() {
  const e = trilha === 'ec7';
  $('d-ec7').hidden = !e; $('d-gz').hidden = e; $('m-ec7').hidden = !e; $('t-ec7').hidden = !e; $('t-gz').hidden = e; $('r-ec7').hidden = !e; $('r-gz').hidden = e;
  renderEc7();
  if (!e) { if (atual === 8) renderTreino(); if (atual === 9) renderResultados(); if (atual === 6) carregarDados(); }
}
const TXT_EC7 = {
  coletar: 'Baixando do Swiss-Prot até 500 enzimas revisadas por classe EC. Proteínas com mais de uma classe são descartadas.',
  preparar: 'O MMseqs2 agrupa as enzimas coletadas para dividir treino e teste sem parentes próximos dos dois lados, e os dados são preparados para o treino.',
  treinar: 'O MLP de 7 classes aprende com validação cruzada em 5 dobras por grupo e depois é medido no teste fixo, que nunca foi usado para escolher nada.',
  continuar: 'Rodando as etapas em sequência, reaproveitando a coleta: agrupar e treinar.',
  tudo: 'Rodando tudo em sequência: coletar, agrupar e treinar. Pode levar vários minutos.',
};
function logEc7(pre) {
  const l = ec7?.log || []; pre.hidden = !l.length; pre.textContent = l.join('\n'); pre.scrollTop = pre.scrollHeight;
}
function renderEc7() {
  if (!ec7) return;
  const r = ec7.resultado || {}; const roda = ec7.rodando;
  const modelo = r.disponivel === true;
  // dados
  const chip = $('d-ec7-chip');
  chip.textContent = roda && ec7.acao === 'coletar' ? 'Coletando…' : modelo ? 'Modelo EC 1–7 disponível' : 'Nenhum modelo ainda';
  chip.className = 'chip ' + (roda && ec7.acao === 'coletar' ? 'run' : modelo ? 'ok' : '');
  $('d-ec7-info').textContent = modelo ? 'Há um modelo treinado (' + fmt(r.proteinas) + ' enzimas). Você pode coletar de novo para treinar outro, ou ir direto aos Resultados.' : 'Colete as enzimas para começar.';
  for (const b of ['d-ec7-coletar', 'm-rodar', 't7-treinar', 't7-continuar', 't7-tudo']) $(b).disabled = Boolean(roda);
  logEc7($('d-ec7-log')); logEc7($('m-log')); logEc7($('t7-log'));
  // agrupar
  const mc = $('m-chip'); mc.textContent = roda && ec7.acao === 'preparar' ? 'Agrupando…' : ec7.codigo_saida === 0 && ec7.acao === 'preparar' ? 'Concluído' : ec7.codigo_saida && ec7.acao === 'preparar' ? 'Falhou · veja o log' : '—';
  // treinar
  const tt = $('t7-titulo'), te = $('t7-estado');
  tt.textContent = roda ? 'Executando: ' + ({ coletar: 'coletar', preparar: 'agrupar', treinar: 'treinar', continuar: 'continuar', tudo: 'tudo' }[ec7.acao] || ec7.acao) : ec7.codigo_saida === 0 ? 'Concluído' : ec7.codigo_saida ? 'Falhou' : 'Pronto';
  te.textContent = roda ? 'Executando' : ec7.codigo_saida === 0 ? 'Concluído' : ec7.codigo_saida ? 'Falhou' : 'Aguardando'; te.className = 'chip ' + (roda ? 'run' : ec7.codigo_saida === 0 ? 'ok' : ec7.codigo_saida ? 'no' : '');
  $('t7-explica').textContent = roda ? TXT_EC7[ec7.acao] || 'Em andamento.' : ec7.codigo_saida ? 'A etapa falhou. Veja o final do log abaixo; o erro costuma explicar o que faltou.' : 'Escolha uma ação acima. Se você acabou de coletar e agrupar, use "Treinar agora".';
  const modo = configInfo?.em_uso?.mmseqs_modo; $('t7-mmseqs').textContent = modo ? rotuloModo(modo) : 'definido em Configurações';
  if (atual === 9 && trilha === 'ec7') renderResultadosEc7();
}
function renderResultadosEc7() {
  const r = ec7?.resultado; if (!r || !r.disponivel) { $('r7-acc').textContent = '—'; $('r7-explica').textContent = 'Ainda não há modelo EC 1–7. Volte aos passos anteriores, colete, agrupe e treine.'; return; }
  const assinatura = (r.pasta || '') + ':' + r.teste.acuracia_balanceada; if (assinatura === resultadoEc7) return; resultadoEc7 = assinatura;
  const acc = r.teste.acuracia_balanceada, cv = r.cv;
  contar($('r7-acc'), acc * 100, v => v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%');
  $('r7-explica').textContent = 'Em enzimas de grupos que o modelo nunca viu, ele acerta a classe cerca de ' + Math.round(acc * 100) + ' vezes a cada 100, considerando as 7 classes com o mesmo peso. Chutar ao acaso acertaria ' + pct(r.acaso) + '.';
  $('r7-cv').textContent = pct(cv.acuracia_balanceada_media) + ' ± ' + (cv.acuracia_balanceada_dp * 100).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  $('r7-n').textContent = fmt(r.teste.n); $('r7-prot').textContent = fmt(r.proteinas) + ' enzimas no total; F1 macro ' + (r.teste.f1_macro).toLocaleString('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + '.';
  $('r7-acaso').textContent = pct(r.acaso);
  const sens = $('r7-sens'); sens.replaceChildren();
  const arr = Array.isArray(r.teste.sensibilidade_por_classe) ? r.teste.sensibilidade_por_classe : r.classes.map(c => r.teste.sensibilidade_por_classe?.[c]);
  r.classes.forEach((c, i) => {
    const v = arr[i]; const li = el('div', undefined, 'comp-linha mlp'); const t = el('span', undefined, 't'); const b = el('i'); t.append(b);
    li.append(el('span', (r.codigos?.[i] ? r.codigos[i] + ' · ' : '') + c), t, el('b', pct(v, 0))); sens.append(li);
    setTimeout(() => { b.style.width = Number.isFinite(v) ? v * 100 + '%' : '0'; }, 60 + i * 50);
  });
  const mx = $('r7-matriz'); mx.replaceChildren(); const m = r.teste.matriz_confusao_linhas_reais_colunas_previstas, k = r.classes.length;
  mx.style.gridTemplateColumns = 'auto repeat(' + k + ', 1fr)';
  mx.append(el('span', '', 'mc cab'));
  for (let j = 0; j < k; j++) mx.append(el('span', r.codigos?.[j] || String(j + 1), 'mc cab'));
  for (let i = 0; i < k; i++) {
    const soma = m[i].reduce((a, b) => a + b, 0) || 1;
    mx.append(el('span', r.codigos?.[i] || String(i + 1), 'mc cab'));
    for (let j = 0; j < k; j++) { const p = m[i][j] / soma; const c = el('span', Math.round(p * 100) + '', 'mc' + (i === j ? ' diag' : '')); c.style.background = 'rgba(19,122,106,' + (0.06 + p * 0.85).toFixed(2) + ')'; c.style.color = p > .5 ? '#fff' : ''; c.title = r.classes[i] + ' → ' + r.classes[j] + ': ' + m[i][j] + ' (' + Math.round(p * 100) + '%)'; mx.append(c); }
  }
  const lim = $('r7-limites'); lim.replaceChildren(); for (const t of r.limites || []) lim.append(el('li', t));
}
let resultadoEc7 = '';
async function acaoEc7(acao) {
  try { await api('/api/ec7', { acao }); await pollEc7(); } catch (e) { $('t7-explica').textContent = e.message; $('d-ec7-info').textContent = e.message; }
}

/* ---------- passo 1: dados ---------- */
async function carregarDados() {
  if (fontesCarregadas) return;
  try {
    const r = await api('/api/fontes'); const sel = $('d-fonte');
    for (const f of r.fontes) { const o = el('option', f.nome + ' · ' + (f.bytes_gz / 1048576).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' MiB'); o.value = f.id; sel.append(o); }
    $('d-fonte-info').textContent = r.fontes.length ? r.fontes.length + ' arquivo(s) encontrado(s) nas pastas do projeto.' : 'Nenhum arquivo .gz encontrado ainda.';
    fontesCarregadas = true;
  } catch (e) { $('d-fonte-info').textContent = e.message; }
}

/* ---------- passo 2: agrupar ---------- */
async function carregarMmseqs() {
  try {
    const [f1, cfg] = await Promise.all([api('/api/fase1'), api('/api/configuracoes')]);
    mmseqsInfo = f1.mmseqs; configInfo = cfg; renderMmseqs();
  } catch (e) { $('m-info').textContent = e.message; }
}
function rotuloModo(m) { return { auto: 'automático', nativo: 'nativo do Windows', wsl: 'WSL' }[m] || m; }
function renderMmseqs() {
  const m = mmseqsInfo; const cartoes = $('m-cartoes');
  if (!m || !m.windows) {
    cartoes.hidden = true; $('m-info').textContent = 'Neste sistema o MMseqs2 é usado diretamente pelo comando mmseqs. Nada a escolher aqui.'; return;
  }
  cartoes.hidden = false;
  $('m-st-nativo').textContent = m.nativo ? 'Instalado' : 'Não instalado'; $('m-st-nativo').className = 'chip ' + (m.nativo ? 'ok' : 'no');
  $('m-st-wsl').textContent = m.wsl ? 'WSL ' + m.distro + ' encontrado' : 'WSL não encontrado'; $('m-st-wsl').className = 'chip ' + (m.wsl ? 'ok' : 'no');
  const modo = configInfo?.em_uso?.mmseqs_modo || 'auto';
  for (const b of cartoes.querySelectorAll('[data-usar]')) {
    const k = b.dataset.usar; b.disabled = k === 'nativo' ? !m.nativo : !m.wsl; b.textContent = modo === k ? 'Em uso ✓' : 'Usar este';
  }
  let texto;
  if (!m.nativo && !m.wsl) texto = 'Nenhum MMseqs2 disponível. Para rodar sem Linux e sem administrador, execute ferramentas\\instalar_mmseqs_nativo.cmd na pasta do projeto e volte a esta tela.';
  else if (!m.nativo) texto = 'Sem permissão de administrador? O modo nativo não precisa dela: execute ferramentas\\instalar_mmseqs_nativo.cmd.';
  else texto = 'Modo atual: ' + rotuloModo(modo) + (modo === 'auto' ? ' (usa o nativo quando instalado, senão o WSL)' : '') + '. Ao trocar, reinicie o sistema para aplicar ao fluxo completo.';
  $('m-info').textContent = texto;
}
async function usarModo(k) {
  try { const r = await api('/api/configuracoes', { mmseqs_modo: k }); configInfo = r; renderMmseqs(); $('m-info').textContent = 'Preferência salva: ' + rotuloModo(k) + '. ' + (r.mensagem || ''); }
  catch (e) { $('m-info').textContent = e.message; }
}

/* ---------- passo 3: treinar ---------- */
const EXPLICA = {
  agrupar: 'O MMseqs2 está comparando as sequências e juntando as parecidas em grupos. Isso reduz repetição e prepara uma divisão justa entre treino e teste.',
  embeddings: 'O ESM-2 lê cada proteína e a transforma em 320 números. É a etapa que mais usa GPU ou CPU.',
  auditoria: 'Conferindo se os vetores e os rótulos estão corretos antes de treinar. Um erro aqui contaminaria todo o resultado.',
  separar: 'Dividindo em treino, validação e teste sem separar membros do mesmo grupo, para o teste ser honesto.',
  treinar: 'O MLP está aprendendo: a cada época ele vê os exemplos de treino e é conferido na validação. Guardamos a melhor época.',
  extrair: 'Lendo os arquivos .gz, validando cada sequência (alfabeto e tamanho de 1 a 512) e escolhendo os candidatos até o limite.',
  mmseqs_inicial: 'O MMseqs2 junta as sequências quase idênticas da entrada e escolhe um representante por grupo, reduzindo repetição.',
  rotular: 'Montando as tabelas e aplicando a regra dos 9 aminoácidos para dar o rótulo Completa ou Incompleta a cada proteína.',
  banco: 'Guardando proteínas, grupos, partições e métricas no banco SQLite desta execução, para consultar depois.',
  consolidar: 'Juntando as peças (vetores, rótulos e grupos) em um só banco para consulta.',
};
function fluxoTarefa(s) { return s.tarefas.find(t => t.etapa === 'fluxo' && t.parametros?.execucao === s.execucao_selecionada); }
function renderTreino() {
  const s = estado; const form = $('t-form'), prog = $('t-prog');
  $('t-r-fonte').textContent = $('d-fonte').selectedOptions[0]?.textContent || 'Todas as fontes';
  $('t-r-limite').textContent = fmt(escolha.limite) + ' sequências candidatas';
  const modo = configInfo?.em_uso?.mmseqs_modo; $('t-r-mmseqs').textContent = modo ? rotuloModo(modo) : 'definido em Configurações';
  const emFluxo = Boolean(execSel && s && s.fluxo);
  form.hidden = emFluxo; prog.hidden = !emFluxo;
  if (s && s.execucoes.length && !emFluxo) $('t-anteriores').textContent = s.execucoes.length + ' execução(ões) anterior(es) existem. Veja os números delas no passo Resultados.'; else $('t-anteriores').textContent = '';
  if (!emFluxo) return;
  const fases = s.fluxo.fases, feitas = fases.filter(f => f.estado === 'concluido').length;
  $('t-barra').style.width = (feitas / fases.length * 100) + '%';
  const corrente = fases.find(f => ['executando', 'falhou', 'recuperacao'].includes(f.estado));
  const tarefa = fluxoTarefa(s);
  const fim = feitas === fases.length;
  $('t-titulo').textContent = fim ? 'Experimento concluído' : corrente ? corrente.nome : 'Na fila…';
  const chip = $('t-estado'); chip.textContent = fim ? 'Concluído' : corrente?.estado === 'falhou' ? 'Falhou' : corrente ? 'Executando' : 'Aguardando'; chip.className = 'chip ' + (fim ? 'ok' : corrente?.estado === 'falhou' ? 'no' : 'run');
  const ol = $('t-fases'); ol.replaceChildren();
  fases.forEach((f, i) => { const li = el('li', undefined, f.estado); li.append(el('b', f.estado === 'concluido' ? '✓' : String(i + 1)), el('span', f.nome), el('span', { concluido: 'Concluído', executando: 'Executando', pendente: 'Aguardando', falhou: 'Falhou' }[f.estado] || f.estado, 'peq')); ol.append(li); });
  $('t-explica').textContent = fim ? 'Tudo pronto. Avance para ver como o modelo se saiu.' : corrente?.erro || EXPLICA[corrente?.id] || 'Cada etapa começa sozinha quando a anterior termina.';
  const p = tarefa?.progresso; $('t-detalhe').textContent = p && p.total ? (p.nome ? p.nome + ' · ' : '') + fmt(p.atual) + ' / ' + fmt(p.total) + ' ' + (p.unidade || '') : '';
  $('t-retomar').hidden = !(tarefa && ['interrompido', 'falhou'].includes(tarefa.estado)); $('t-nova').hidden = !fim && !corrente?.erro;
}
async function iniciarFluxo() {
  const b = $('t-iniciar'); b.disabled = true;
  try { const r = await api('/api/execucoes', { limite: escolha.limite, fonte: $('d-fonte').value || 'todas' }); execSel = r.execucao; await poll(); }
  catch (e) { $('t-anteriores').textContent = e.message; }
  finally { b.disabled = false; }
}

/* ---------- passo 4: resultados ---------- */
function contar(caixa, alvo, fmtFn) {
  if (reduzido) { caixa.textContent = fmtFn(alvo); return; }
  const t0 = performance.now(); const dur = 900;
  const passo = t => { const k = Math.min(1, (t - t0) / dur); caixa.textContent = fmtFn(alvo * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(passo); };
  requestAnimationFrame(passo);
}
let resultadoDesenhado = '';
function renderResultados(vindoDoPoll) {
  const s = estado; if (!s) return;
  const sel = $('r-exec'); const ids = ['original', ...s.execucoes.map(x => x.id)];
  if ([...sel.options].map(o => o.value).join('|') !== ids.join('|')) {
    sel.replaceChildren(); const o0 = el('option', 'Base original · 1 milhão'); o0.value = 'original'; sel.append(o0);
    for (const e of s.execucoes) { const o = el('option', e.id + ' · ' + fmt(e.limite) + ' candidatos'); o.value = e.id; sel.append(o); }
  }
  if (document.activeElement !== sel) sel.value = s.execucao_selecionada;
  const r = s.resumo; if (!r) return;
  const assinatura = s.execucao_selecionada + ':' + r.vetores + ':' + (r.teste?.acuracia_balanceada ?? '');
  if (vindoDoPoll && assinatura === resultadoDesenhado) return;
  resultadoDesenhado = assinatura;
  const acc = r.teste?.acuracia_balanceada;
  if (Number.isFinite(acc)) {
    contar($('r-acc'), acc * 100, v => v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%');
    $('r-explica').textContent = 'Em 100 proteínas que o modelo nunca viu, ele classifica corretamente cerca de ' + Math.round(acc * 100) + ', considerando as duas classes com o mesmo peso. É uma medida de prova de conceito: o rótulo é uma regra simples, não um julgamento biológico.';
  } else { $('r-acc').textContent = '—'; $('r-explica').textContent = 'Esta execução ainda não tem resultado de teste. Se ela está em andamento, volte ao passo Treinar.'; }
  $('r-vet').textContent = fmt(r.vetores); $('r-gru').textContent = fmt(r.grupos);
  const c = r.rotulos?.Completa, i = r.rotulos?.Incompleta; $('r-rot').textContent = Number.isFinite(c) ? fmt(c) + ' / ' + fmt(i) : '—';
  const comp = $('r-comp'); comp.replaceChildren();
  const linhas = [['MLP sobre ESM-2', r.teste, true], ['Classe majoritária', r.baseline, false], ['Regra direta', r.regra, false]];
  for (const [nome, d, mlp] of linhas) {
    const v = d?.acuracia_balanceada; const li = el('div', undefined, 'comp-linha' + (mlp ? ' mlp' : ''));
    const t = el('span', undefined, 't'); const barra = el('i'); t.append(barra);
    li.append(el('span', nome), t, el('b', pct(v))); comp.append(li);
    setTimeout(() => { barra.style.width = Number.isFinite(v) ? v * 100 + '%' : '0'; }, 60);
  }
}

/* ---------- passo 5: consultar ---------- */
function acompanharConsulta(s) {
  const t = s.tarefas.find(x => x.id === consultaId); if (!t) return;
  const est = $('c-estado');
  if (t.estado === 'concluido' && t.resultado) { renderConsulta(t.resultado); est.textContent = 'Consulta #' + t.id + ' concluída.'; consultaId = null; $('c-enviar').disabled = false; }
  else if (['falhou', 'interrompido', 'cancelado', 'recuperacao'].includes(t.estado)) { est.textContent = t.erro || t.estado; consultaId = null; $('c-enviar').disabled = false; }
  else est.textContent = 'Consulta #' + t.id + ' · ' + t.estado + (s.pausado ? ' · fila pausada' : '');
}
function renderConsulta(r) {
  const box = $('c-saida'); box.replaceChildren();
  if (r.ec7) { const p = el('div', undefined, 'principal'); p.append(el('span', 'MODELO PRINCIPAL · EC 1–7'), el('strong', r.ec7.classe + ' (' + r.ec7.ec + ')'), el('span', 'Confiança ' + pct(r.ec7.confianca) + ' (não calibrada)'));
    const rk = el('div', undefined, 'ranking'); for (const x of (r.ec7.ranking || []).slice(0, 3)) { const lin = el('div', undefined, 'rk-linha'); const t = el('span', undefined, 't'); const b = el('i'); b.style.width = Math.max(2, x.escore * 100) + '%'; t.append(b); lin.append(el('span', x.ec + ' · ' + x.classe), t, el('b', pct(x.escore, 1))); rk.append(lin); }
    p.append(rk); box.append(p); }
  const extra = el('details', undefined, 'outros'); extra.append(el('summary', 'Ver outros modelos (complementar e prova de conceito)')); if (!r.ec7) extra.open = true;
  const cards = el('div', undefined, 'res-cards');
  for (const [rot, val] of [['Regra direta', r.regra_direta], ['IA (MLP)', r.predicao_mlp]]) { const d = el('div'); d.append(el('span', rot), el('strong', val)); cards.append(d); }
  extra.append(cards, el('div', r.concorda_com_regra_direta ? 'Regra e IA concordam.' : 'Regra e IA divergem. A regra direta continua sendo a referência.', 'concorda' + (r.concorda_com_regra_direta ? '' : ' nao')));
  const ess = el('div', undefined, 'essenciais'); for (const a of ESSENCIAIS) { const falta = r.aminoacidos_essenciais_ausentes?.includes(a); ess.append(el('span', a + (falta ? ' ✕' : ' ✓'), falta ? '' : 'ok')); }
  extra.append(el('p', 'Nove aminoácidos essenciais', 'peq'), ess);
  if (r.ec) extra.append(el('p', 'Modelo complementar EC 2 × EC 3: ' + r.ec.predicao + ' (confiança ' + pct(r.ec.confianca) + ', não calibrada)', 'peq'));
  box.append(extra);
  box.append(el('p', fmt(r.residuos) + ' resíduos. O modelo sempre escolhe uma classe, mesmo para proteínas que não são enzimas.', 'peq'));
}
async function enviarConsulta() {
  const b = $('c-enviar'); b.disabled = true;
  try { const r = await api('/api/prever', { sequencia: $('c-seq').value, execucao: execSel || 'original' }); consultaId = r.tarefa_id; $('c-estado').textContent = 'Consulta #' + consultaId + ' adicionada à fila.'; await poll(); }
  catch (e) { $('c-estado').textContent = e.message; b.disabled = false; }
}

/* ---------- passo 6: aprender ---------- */
const RECURSOS = [
  ['Livros e cursos abertos', [
    ['NCBI Bookshelf', 'Livros gratuitos de biomedicina e ciências da vida.', 'https://www.ncbi.nlm.nih.gov/books/'],
    ['OpenStax', 'Livros-texto abertos, incluindo biologia.', 'https://openstax.org'],
    ['LibreTexts Biology', 'Livros dinâmicos e gratuitos de biologia.', 'https://bio.libretexts.org'],
    ['MIT OpenCourseWare', 'Materiais de cursos universitários do MIT.', 'https://ocw.mit.edu'],
    ['Open Textbook Library', 'Livros-texto abertos revisados por pares.', 'https://open.umn.edu/opentextbooks'],
    ['DOAB', 'Milhares de livros de acesso aberto revisados por pares.', 'https://www.doabooks.org'],
    ['OAPEN Library', 'Grande acervo de livros acadêmicos abertos.', 'https://www.oapen.org'],
    ['MERLOT', 'Recursos educacionais abertos selecionados.', 'https://www.merlot.org'],
    ['Wikibooks', 'Livros e guias educacionais escritos de forma colaborativa.', 'https://www.wikibooks.org'],
    ['NPTEL', 'Cursos de universidades indianas (em inglês).', 'https://nptel.ac.in'],
    ['SWAYAM', 'Cursos online gratuitos de instituições indianas.', 'https://swayam.gov.in'],
  ]],
  ['Bibliotecas e acervos', [
    ['Internet Archive', 'Biblioteca digital imensa, com livros para empréstimo.', 'https://archive.org'],
    ['HathiTrust', 'Biblioteca digital acadêmica de várias áreas científicas.', 'https://www.hathitrust.org'],
    ['Google Livros', 'Busca e prévia de publicações de biotecnologia.', 'https://books.google.com'],
    ['Project Gutenberg', 'Obras de domínio público, boas para a história da ciência.', 'https://www.gutenberg.org'],
  ]],
  ['Artigos científicos abertos', [
    ['PubMed Central', 'Artigos completos e gratuitos de pesquisa biomédica.', 'https://pmc.ncbi.nlm.nih.gov'],
    ['Europe PMC', 'Literatura de ciências da vida e biomedicina.', 'https://europepmc.org'],
    ['BioMed Central', 'Pesquisa de acesso aberto em biologia, biotecnologia e medicina.', 'https://www.biomedcentral.com'],
    ['Frontiers', 'Artigos e revisões abertas em várias áreas das ciências da vida.', 'https://www.frontiersin.org'],
  ]],
  ['Ferramentas e dados deste projeto', [
    ['NCBI', 'De onde vêm as sequências de proteínas.', 'https://www.ncbi.nlm.nih.gov'],
    ['UniProt / Swiss-Prot', 'Proteínas revisadas, usadas no experimento EC7.', 'https://www.uniprot.org'],
    ['MMseqs2', 'Agrupamento e busca rápida de sequências.', 'https://github.com/soedinglab/MMseqs2'],
    ['ESM (Meta AI)', 'Família de modelos de linguagem para proteínas.', 'https://github.com/facebookresearch/esm'],
  ]],
];
const GLOSSARIO = [
  ['Aminoácido', 'Bloco que forma as proteínas. Existem 20 tipos, cada um com uma letra.'],
  ['Sequência', 'A ordem dos aminoácidos de uma proteína, escrita como um texto.'],
  ['FASTA', 'Formato de arquivo de texto para sequências, com um cabeçalho e as letras.'],
  ['Grupo (cluster)', 'Conjunto de sequências parecidas, reunidas pelo MMseqs2.'],
  ['Identidade e cobertura', 'Quanto das letras coincidem e quanto da sequência é comparado. O projeto usa 50% e 80%.'],
  ['Embedding', 'Lista de 320 números que resume uma proteína, gerada pelo ESM-2.'],
  ['MLP', 'Rede neural simples que recebe o embedding e devolve uma classe.'],
  ['Acurácia balanceada', 'Média do acerto em cada classe. Evita que a classe mais comum esconda erros.'],
  ['Vazamento', 'Quando o teste se parece demais com o treino e a nota fica melhor que a realidade.'],
  ['Calibração', 'Se um escore de 80% de fato acerta 80% das vezes. Os escores do MLP ainda não são calibrados.'],
  ['EC (Enzyme Commission)', 'Sistema de classificação de enzimas em 7 classes principais.'],
];
let aprenderMontado = false;
function montarAprender() {
  if (aprenderMontado) return; aprenderMontado = true;
  const box = $('a-grupos');
  for (const [titulo, itens] of RECURSOS) {
    const g = el('section', undefined, 'grupo-rec'); g.append(el('h3', titulo)); const lista = el('div', undefined, 'recs');
    for (const [nome, desc, url] of itens) { const a = el('a', undefined, 'rec'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.append(el('b', nome), el('span', desc)); lista.append(a); }
    g.append(lista); box.append(g);
  }
  const dl = $('a-gloss'); for (const [t, d] of GLOSSARIO) dl.append(el('dt', t), el('dd', d));
}

/* ---------- eventos ---------- */
function ligar() {
  $('voltar').addEventListener('click', () => ir(atual - 1));
  $('avancar').addEventListener('click', () => ir(atual + 1));
  document.addEventListener('click', ev => { const b = ev.target.closest('[data-ir]'); if (b) ir(Number(b.dataset.ir)); });
  document.addEventListener('keydown', ev => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    if (ev.key === 'ArrowRight') ir(atual + 1); else if (ev.key === 'ArrowLeft') ir(atual - 1);
  });
  $('seq-demo').addEventListener('input', atualizarDemo);
  document.querySelectorAll('[data-seq]').forEach(b => b.addEventListener('click', () => { $('seq-demo').value = b.dataset.seq; atualizarDemo(); }));
  $('id-slider').addEventListener('input', demoCluster);
  $('d-limite').addEventListener('click', ev => { const b = ev.target.closest('.opc'); if (!b) return; escolha.limite = Number(b.dataset.v); document.querySelectorAll('#d-limite .opc').forEach(o => o.setAttribute('aria-checked', String(o === b))); });
  $('d-fonte').addEventListener('change', () => { escolha.fonte = $('d-fonte').value; });
  document.querySelectorAll('[data-usar]').forEach(b => b.addEventListener('click', () => usarModo(b.dataset.usar)));
  $('t-iniciar').addEventListener('click', iniciarFluxo);
  $('d-trilha').addEventListener('click', ev => { const b = ev.target.closest('[data-trilha]'); if (b) definirTrilha(b.dataset.trilha); });
  $('d-ec7-coletar').addEventListener('click', () => acaoEc7('coletar'));
  $('m-rodar').addEventListener('click', () => acaoEc7('preparar'));
  $('t7-treinar').addEventListener('click', () => acaoEc7('treinar'));
  $('t7-continuar').addEventListener('click', () => acaoEc7('continuar'));
  $('t7-tudo').addEventListener('click', () => acaoEc7('tudo'));
  $('t-retomar').addEventListener('click', async () => { try { await api('/api/retomar-fluxo', { execucao: execSel }); await poll(); } catch (e) { $('t-detalhe').textContent = e.message; } });
  $('t-nova').addEventListener('click', () => { execSel = null; poll(); renderTreino(); });
  $('r-exec').addEventListener('change', () => { execSel = $('r-exec').value === 'original' ? null : $('r-exec').value; resultadoDesenhado = ''; poll(); });
  $('c-seq').addEventListener('input', () => { $('c-tam').textContent = limparSeq($('c-seq').value).length + ' / 512 resíduos'; renderLetras($('c-letras'), $('c-seq').value.slice(0, 60)); });
  $('c-exemplo').addEventListener('click', () => { $('c-seq').value = 'MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVV'; $('c-seq').dispatchEvent(new Event('input')); });
  $('c-enviar').addEventListener('click', enviarConsulta);
}

function montarClasses() { const ul = $('d-classes'); for (const [c, n, d] of CLASSES_EC) { const li = el('li'); li.append(el('b', c + ' · ' + n), el('span', ' ' + d)); ul.append(li); } }
montarTrilha(); montarClasses(); montarHelice(); atualizarDemo(); demoCluster(); demoRede(); demoBarras(); montarAbas(); ligar();
{
  const m = /^#p(\d+)$/.exec(location.hash); ir(m ? Number(m[1]) : 0);
}
poll(); setInterval(poll, 2000);
