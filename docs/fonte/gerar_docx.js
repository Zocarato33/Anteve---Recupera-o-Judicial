// Converte o markdown exportado dos documentos em .docx com a identidade SBK (Brand Book 2026).
// Uso: node gerar_docx.js entrada.md saida.docx "Subtítulo" [paginas.json]
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, ExternalHyperlink, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, HeadingLevel, Header, Footer, PageNumber,
  PageBreak, TabStopType, TabStopPosition, VerticalAlign, TableLayoutType,
} = require("docx");

const [, , entrada, saida, subtitulo, paginasArq] = process.argv;
const paginas = paginasArq && fs.existsSync(paginasArq) ? JSON.parse(fs.readFileSync(paginasArq, "utf8")) : {};

const COR = { verde: "023631", ciano: "075056", verdeClaro: "0A5A52", off: "ECEFF3", chumbo: "4A545E", linha: "E0E0E0", branco: "FFFFFF" };
const FONTE_CORPO = "Calibri Light";
const FONTE_TITULO = "Calibri";
const LARGURA = 8788; // A4 menos margens de 3 cm e 2,5 cm, em DXA

const md = fs.readFileSync(entrada, "utf8").replace(/\r/g, "");
const linhas = md.split("\n");
const titulo = linhas[0].replace(/^#\s+/, "").trim();
const nomeCurto = titulo.replace(/^Antevê:\s*/, "");

// ------------------------------------------------------------ texto inline
function runs(texto, base = {}) {
  const out = [];
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g;
  let ult = 0, m;
  const limpar = (s) => s.replace(/\\([_*\[\]()#`|-])/g, "$1");
  const add = (t, extra = {}) => { if (t) out.push(new TextRun({ text: limpar(t), font: base.font || FONTE_CORPO, size: base.size || 22, color: base.color || "000000", bold: base.bold, ...extra })); };
  while ((m = re.exec(texto))) {
    add(texto.slice(ult, m.index));
    if (m[2]) add(m[2], { font: FONTE_TITULO, bold: true, color: base.color || "000000" });
    else if (m[3]) add(m[3], { font: "Consolas", size: (base.size || 22) - 2, color: COR.ciano });
    else if (m[4]) out.push(new ExternalHyperlink({ link: m[5], children: [new TextRun({ text: limpar(m[4]), font: base.font || FONTE_CORPO, size: base.size || 22, color: COR.ciano, underline: {} })] }));
    ult = re.lastIndex;
  }
  add(texto.slice(ult));
  return out;
}

// ------------------------------------------------------------ blocos
function titulo1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, spacing: { before: 0, after: 160 }, keepNext: true, children: [new TextRun({ text: t, font: FONTE_TITULO, bold: true, size: 36, color: COR.verde })], border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: COR.verde, space: 6 } } }); }
function titulo2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 100 }, keepNext: true, children: [new TextRun({ text: t, font: FONTE_TITULO, bold: true, size: 28, color: COR.ciano })] }); }
function titulo3(t) { return new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 60 }, keepNext: true, children: [new TextRun({ text: t, font: FONTE_TITULO, bold: true, size: 24, color: COR.verdeClaro })] }); }
function paragrafo(t) { return new Paragraph({ spacing: { after: 120, line: 276 }, children: runs(t) }); }

let instanciaLista = 0;
function itemLista(t, tipo, nivel, instancia) {
  let texto = t, marcado = false;
  if (tipo === "check") { marcado = /^\[x\]/i.test(texto); texto = texto.replace(/^\[[ xX]\]\s*/, ""); }
  const filhos = tipo === "check" ? [new TextRun({ text: marcado ? "☑  " : "☐  ", font: "Segoe UI Symbol", size: 22, color: COR.ciano }), ...runs(texto)] : runs(texto);
  const p = { spacing: { after: 80, line: 276 }, children: filhos };
  if (tipo === "ordered") p.numbering = { reference: "numerada", level: nivel, instance: instancia };
  else if (tipo === "bullet") p.numbering = { reference: "marcador", level: nivel };
  else p.indent = { left: 360 };
  return new Paragraph(p);
}

function celula(texto, largura, cabecalho, zebra) {
  return new TableCell({
    width: { size: largura, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, color: "auto", fill: cabecalho ? COR.verde : (zebra ? COR.off : COR.branco) },
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    verticalAlign: VerticalAlign.CENTER,
    borders: { top: { style: BorderStyle.SINGLE, size: 4, color: COR.linha }, bottom: { style: BorderStyle.SINGLE, size: 4, color: COR.linha }, left: { style: BorderStyle.NONE, size: 0, color: "auto" }, right: { style: BorderStyle.NONE, size: 0, color: "auto" } },
    children: [new Paragraph({ spacing: { after: 0, line: 252 }, children: runs(texto, cabecalho ? { font: FONTE_TITULO, bold: true, size: 19, color: COR.branco } : { size: 19 }) })],
  });
}

function tabela(linhasTab) {
  const cels = linhasTab.map((l) => l.replace(/^\|/, "").replace(/\|\s*$/, "").split(/(?<!\\)\|/).map((c) => c.trim()));
  const n = cels[0].length;
  // mínimo: a maior palavra da coluna cabe inteira (cerca de 105 DXA por caractere em 9,5 pt, mais margens);
  // o restante é distribuído pelo comprimento médio do texto de cada coluna
  const txt = (c) => (c || "").replace(/\*\*|`|\\/g, "");
  const minimo = Array.from({ length: n }, (_, i) => 200 + 105 * Math.max(...cels.map((r, k) => Math.max(...txt(r[i]).split(/\s+/).map((w) => w.length * (k === 0 ? 1.08 : 1))))));
  const media = Array.from({ length: n }, (_, i) => Math.max(4, cels.reduce((a, r) => a + txt(r[i]).length, 0) / cels.length));
  let larguras = minimo.slice();
  const sobra = LARGURA - minimo.reduce((a, b) => a + b, 0);
  if (sobra > 0) { const sm = media.reduce((a, b) => a + b, 0); larguras = minimo.map((m, i) => m + Math.floor((media[i] / sm) * sobra)); }
  else { const sm = minimo.reduce((a, b) => a + b, 0); larguras = minimo.map((m) => Math.floor((m / sm) * LARGURA)); }
  larguras[n - 1] += LARGURA - larguras.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: LARGURA, type: WidthType.DXA }, columnWidths: larguras, layout: TableLayoutType.FIXED,
    rows: cels.map((r, i) => new TableRow({ tableHeader: i === 0, cantSplit: true, children: larguras.map((w, j) => celula(r[j] || "", w, i === 0, i % 2 === 0)) })),
  });
}

function chamada(t) { // caixa de destaque: fundo Off White e borda esquerda Ciano Escuro
  return new Paragraph({ spacing: { before: 120, after: 160, line: 276 }, shading: { type: ShadingType.CLEAR, color: "auto", fill: COR.off },
    border: { left: { style: BorderStyle.SINGLE, size: 24, color: COR.ciano, space: 8 } }, indent: { left: 180, right: 120 }, children: runs(t, { color: COR.verde }) });
}

function fluxoMermaid(codigo) { // o diagrama vira uma tabela de etapas, legível no Word
  const nos = [];
  for (const m of codigo.matchAll(/(\w)\[([^\]]+)\]/g)) if (!nos.find((n) => n.id === m[1])) nos.push({ id: m[1], rotulo: m[2].split("<br/>") });
  const ordem = ["A", "B", "C", "D", "H", "E", "F", "G"].map((id) => nos.find((n) => n.id === id)).filter(Boolean);
  const rot = { H: "Em paralelo, completa evidências, partes e CNPJ", E: "Quando há dúvida", F: "Só RJ confirmada", G: "Com gates de qualidade" };
  return tabela(["| Etapa | O que acontece |", "| --- | --- |", ...ordem.map((n, i) => `| ${i + 1}. ${n.rotulo[0]} | ${n.rotulo[1] ? n.rotulo[1].charAt(0).toUpperCase() + n.rotulo[1].slice(1) : rot[n.id] || ""} |`)]);
}

// ------------------------------------------------------------ capa e sumário
function capa() {
  const vazio = (h) => new Paragraph({ spacing: { before: h, after: 0 }, children: [] });
  const blocoEscuro = new Table({
    width: { size: LARGURA, type: WidthType.DXA }, columnWidths: [LARGURA], layout: TableLayoutType.FIXED,
    rows: [new TableRow({ height: { value: 5200, rule: "atLeast" }, children: [new TableCell({
      width: { size: LARGURA, type: WidthType.DXA }, shading: { type: ShadingType.CLEAR, color: "auto", fill: COR.verde },
      margins: { top: 600, bottom: 600, left: 600, right: 600 }, verticalAlign: VerticalAlign.BOTTOM,
      borders: { top: { style: BorderStyle.NONE, size: 0, color: "auto" }, bottom: { style: BorderStyle.NONE, size: 0, color: "auto" }, left: { style: BorderStyle.NONE, size: 0, color: "auto" }, right: { style: BorderStyle.NONE, size: 0, color: "auto" } },
      children: [
        new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "ANTEVÊ", font: FONTE_TITULO, bold: true, size: 24, color: COR.off, characterSpacing: 40 })] }),
        new Paragraph({ spacing: { after: 240, line: 312 }, children: [new TextRun({ text: nomeCurto, font: FONTE_TITULO, bold: true, size: 60, color: COR.branco })] }),
        new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: subtitulo, font: FONTE_CORPO, size: 28, color: COR.off })] }),
      ] })] })],
  });
  // sistema de cards: três faixas arredondadas no espectro verde, como elemento de apoio
  const cards = new Table({
    width: { size: 3000, type: WidthType.DXA }, columnWidths: [1000, 1000, 1000], layout: TableLayoutType.FIXED,
    rows: [new TableRow({ height: { value: 160, rule: "exact" }, children: [COR.verde, COR.ciano, "2A7C79"].map((c) => new TableCell({ width: { size: 1000, type: WidthType.DXA }, shading: { type: ShadingType.CLEAR, color: "auto", fill: c },
      borders: { top: { style: BorderStyle.SINGLE, size: 24, color: COR.branco }, bottom: { style: BorderStyle.SINGLE, size: 24, color: COR.branco }, left: { style: BorderStyle.SINGLE, size: 24, color: COR.branco }, right: { style: BorderStyle.SINGLE, size: 24, color: COR.branco } }, children: [new Paragraph({ children: [] })] })) })],
  });
  return [
    new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: "SBK IA", font: FONTE_TITULO, bold: true, size: 26, color: COR.verde })] }),
    vazio(2400), cards, vazio(200), blocoEscuro, vazio(900),
    new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Versão 1.0 | 22/09/2026", font: FONTE_CORPO, size: 22, color: COR.chumbo })] }),
    new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Autor: Joao Zocarato", font: FONTE_CORPO, size: 22, color: COR.chumbo })] }),
    new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: "Classificação sujeita a validação jurídica. Uso interno SBK.", font: FONTE_CORPO, size: 20, color: COR.chumbo })] }),
  ];
}

function sumario(itens) {
  const out = [new Paragraph({ pageBreakBefore: true, spacing: { after: 240 }, children: [new TextRun({ text: "Sumário", font: FONTE_TITULO, bold: true, size: 36, color: COR.verde })], border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: COR.verde, space: 6 } } })];
  for (const it of itens) {
    const pg = paginas[it.texto] != null ? String(paginas[it.texto]) : "00";
    out.push(new Paragraph({ spacing: { after: it.nivel === 1 ? 100 : 40 }, indent: { left: it.nivel === 1 ? 0 : 360 },
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX, leader: "dot" }],
      children: [new TextRun({ text: it.texto, font: it.nivel === 1 ? FONTE_TITULO : FONTE_CORPO, bold: it.nivel === 1, size: it.nivel === 1 ? 22 : 20, color: it.nivel === 1 ? COR.verde : "000000" }),
        new TextRun({ text: "\t" + pg, font: FONTE_CORPO, size: 20, color: COR.chumbo })] }));
  }
  return out;
}

// ------------------------------------------------------------ parser
const corpo = [];
const indice = [];
let i = 1;
while (i < linhas.length && !linhas[i].startsWith("## ")) i++; // pula a linha de data e autor
let lista = null; // {tipo, instance}
function fecharLista() { lista = null; }
while (i < linhas.length) {
  const l = linhas[i];
  if (!l.trim()) { i++; continue; }
  if (l.startsWith("```")) {
    const lang = l.slice(3).trim(); const buf = []; i++;
    while (i < linhas.length && !linhas[i].startsWith("```")) buf.push(linhas[i++]);
    i++; fecharLista();
    if (lang === "mermaid") corpo.push(fluxoMermaid(buf.join("\n")));
    else buf.forEach((b) => corpo.push(new Paragraph({ children: [new TextRun({ text: b, font: "Consolas", size: 18 })] })));
    continue;
  }
  if (l.startsWith("## ")) { fecharLista(); const t = l.slice(3).trim(); indice.push({ nivel: 1, texto: t }); corpo.push(titulo1(t)); i++; continue; }
  if (l.startsWith("### ")) { fecharLista(); const t = l.slice(4).trim(); indice.push({ nivel: 2, texto: t }); corpo.push(titulo2(t)); i++; continue; }
  if (l.startsWith("#### ")) { fecharLista(); corpo.push(titulo3(l.slice(5).trim())); i++; continue; }
  if (l.startsWith("|")) {
    fecharLista(); const buf = [];
    while (i < linhas.length && linhas[i].startsWith("|")) buf.push(linhas[i++]);
    corpo.push(tabela(buf.filter((r) => !/^\|\s*-{3}/.test(r))));
    corpo.push(new Paragraph({ spacing: { after: 80 }, children: [] }));
    continue;
  }
  const mLista = l.match(/^(\s*)(-|\d+\.)\s+(.*)$/);
  if (mLista) {
    const nivel = Math.min(2, Math.floor(mLista[1].length / 4));
    let tipo = mLista[2] === "-" ? (/^\[[ xX]\]/.test(mLista[3]) ? "check" : "bullet") : "ordered";
    if (nivel === 0 && (!lista || lista.tipo !== tipo)) lista = { tipo, instance: ++instanciaLista };
    corpo.push(itemLista(mLista[3], tipo, nivel, lista ? lista.instance : ++instanciaLista));
    i++; continue;
  }
  fecharLista();
  // "**Atenção:**" e "**Aviso:**" viram chamadas de destaque
  if (/^\*\*(Atenção|Aviso)[:.]/.test(l)) corpo.push(chamada(l)); else corpo.push(paragrafo(l));
  i++;
}

const numeracao = {
  config: [
    { reference: "marcador", levels: [0, 1, 2].map((n) => ({ level: n, format: LevelFormat.BULLET, text: n === 1 ? "◦" : "●", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 360 + n * 360, hanging: 260 } }, run: { color: COR.ciano, font: "Calibri" } } })) },
    { reference: "numerada", levels: [0, 1, 2].map((n) => ({ level: n, format: n === 0 ? LevelFormat.DECIMAL : LevelFormat.LOWER_LETTER, text: n === 0 ? "%1." : "%2)", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 360 + n * 360, hanging: 300 } }, run: { color: COR.verde, bold: true, font: FONTE_TITULO } } })) },
  ],
};

const cabecalho = new Header({ children: [new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: COR.verde, space: 4 } },
  tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
  children: [new TextRun({ text: "Antevê", font: FONTE_TITULO, bold: true, size: 20, color: COR.verde }), new TextRun({ text: "  |  SBK IA", font: FONTE_CORPO, size: 20, color: COR.ciano }),
    new TextRun({ text: "\t" + nomeCurto, font: FONTE_CORPO, size: 18, color: COR.chumbo })] })] });
const rodape = new Footer({ children: [new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 4, color: COR.linha, space: 4 } },
  tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
  children: [new TextRun({ text: `Antevê | ${nomeCurto} | SBK`, font: FONTE_CORPO, size: 18, color: COR.chumbo }),
    new TextRun({ children: ["\tPágina ", PageNumber.CURRENT], font: FONTE_CORPO, size: 18, color: COR.chumbo })] })] });

const doc = new Document({
  creator: "Joao Zocarato", title: titulo, description: subtitulo,
  styles: { default: { document: { run: { font: FONTE_CORPO, size: 22 }, paragraph: { spacing: { line: 276 } } } } },
  numbering: numeracao,
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1417, bottom: 1417, left: 1701, right: 1417, header: 708, footer: 708 } }, titlePage: true },
    headers: { default: cabecalho, first: new Header({ children: [new Paragraph({ children: [] })] }) },
    footers: { default: rodape, first: new Footer({ children: [new Paragraph({ children: [] })] }) },
    children: [...capa(), ...sumario(indice), ...corpo],
  }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(saida, b); fs.writeFileSync(saida + ".indice.json", JSON.stringify(indice)); console.log("ok", saida, indice.length, "itens"); });
