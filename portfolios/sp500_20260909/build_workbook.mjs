import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const dir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.resolve(dir, '../../outputs/01a08599-dd56-71d0-8f8e-c239feafefd1');
const read = async name => JSON.parse((await fs.readFile(path.join(dir, name), 'utf8')).replace(/^\uFEFF/, ''));
const [portfolio, predict, investor, risk, audit] = await Promise.all([
  read('sp500_portfolio.json'), read('sp500_predict.json'), read('investor_analyses.json'), read('sp500_risk.json'), read('validation_summary.json')
]);
await fs.mkdir(outputDir, { recursive: true });
const wb = Workbook.create();
const allocation = wb.worksheets.add('포트폴리오');
const ranking = wb.worksheets.add('전체 순위');
const detail = wb.worksheets.add('독립 투자자 분석');
const evidence = wb.worksheets.add('위험과 근거');
const color = { navy:'#253B55', text:'#172B42', muted:'#526579', light:'#EDF2F7', amber:'#FFF3D6' };
const percent = '0.0%;(0.0%);"-"';
const signals = {bullish:'긍정', neutral:'중립', bearish:'부정'};
const names = {buffett:'버핏', lynch:'린치', fisher:'피셔'};
function base(sheet, range, widths) {
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = {name:'Arial', size:11, color:color.text};
  sheet.getRange(range).format.rowHeight = 23;
  sheet.getRange(range).format.verticalAlignment = 'center';
  widths.forEach((width, i) => {sheet.getRangeByIndexes(0,i,range.match(/\d+$/)[0] * 1,1).format.columnWidth=width;});
}
function title(sheet, text) {
  sheet.getRange('A2').values=[[text]];
  sheet.getRange('A2').format.font={bold:true,size:16,color:color.navy};
  sheet.getRange('A2').format.rowHeight=30;
}
function header(sheet, row, labels) {
  const r=sheet.getRangeByIndexes(row-1,0,1,labels.length);
  r.values=[labels];
  r.format={fill:color.navy,font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30,verticalAlignment:'center',horizontalAlignment:'center'};
}
function stripe(sheet, row, count, cols) {
  for(let i=0;i<count;i++) if(i%2===1) sheet.getRangeByIndexes(row-1+i,0,1,cols).format.fill=color.light;
}

const holdings = [...audit.included].sort((a,b)=>b.weight-a.weight);
const start=9, last=start+holdings.length-1, cashRow=last+1, totalRow=last+2;
base(allocation,`A1:G${totalRow+13}`,[11,32,24,13,17,13,13]);
allocation.tabColor=color.navy;
title(allocation,'S&P 500 연구 포트폴리오');
allocation.getRange('A3').values=[[`분석 ${portfolio.analysis_date}  /  가격 ${risk.market_regime.as_of_date} 미국 종가  /  USD 기준`]];
allocation.getRange('A5').values=[[`시장 목표 현금 ${(risk.market_regime.target_cash_weight*100).toFixed(2)}%. 편입 후보 부족과 비중 상한으로 최종 현금 ${(portfolio.cash_weight*100).toFixed(1)}%.`]];
allocation.getRange('A6').values=[['성과 미검증(prior_only). 실제 주문용 지시나 미래 수익률 예측이 아님.']];
allocation.getRange('A6:G6').format.fill=color.amber;
header(allocation,8,['티커','회사','섹터','비중','과거 연변동성','긍정 관점','순위 점수']);
allocation.getRange(`A${start}:G${last}`).values=holdings.map(r=>[r.ticker,r.company_name,r.sector,portfolio.weights[r.ticker],risk.annualized_volatility[r.ticker],`${r.bullish_count}/3`,r.total_score]);
stripe(allocation,start,holdings.length,7);
allocation.getRange(`D${start}:E${last}`).setNumberFormat(percent);
allocation.getRange(`G${start}:G${last}`).setNumberFormat('0.00');
allocation.getRange(`D${start}:G${last}`).format.horizontalAlignment='right';
allocation.getRange(`A${cashRow}:G${cashRow}`).values=[['현금','USD 현금 보유분','현금',portfolio.cash_weight,null,null,null]];
allocation.getRange(`D${cashRow}`).setNumberFormat(percent);
allocation.getRange(`A${totalRow}`).values=[['합계']];
allocation.getRange(`D${totalRow}`).formulas=[[`=SUM(D${start}:D${cashRow})`]];
allocation.getRange(`D${totalRow}`).setNumberFormat(percent);
allocation.getRange(`A${totalRow}:G${totalRow}`).format.font.bold=true;
allocation.getRange(`A${totalRow}:G${totalRow}`).format.borders={top:{style:'thin',color:color.navy}};
const metricsRow=totalRow+3;
const summary=[
  ['종목 수',holdings.length],
  ['시장 목표 현금',risk.market_regime.target_cash_weight],
  ['포트폴리오 과거 연변동성',audit.historical_annualized_portfolio_volatility],
  ['최대 종목 비중',Math.max(...Object.values(portfolio.weights))],
  ['최대 섹터 비중',Math.max(...Object.values(audit.sector_weights))]
];
allocation.getRangeByIndexes(metricsRow-1,0,summary.length,1).values=summary.map(r=>[r[0]]);
allocation.getRangeByIndexes(metricsRow-1,3,summary.length,1).values=summary.map(r=>[r[1]]);
allocation.getRange(`D${metricsRow+1}:D${metricsRow+4}`).setNumberFormat(percent);
allocation.getRange(`A${metricsRow+6}`).values=[['상한: 종목 15%, 섹터 35%. 최소 편입 비중 2%. 잔여 비중은 현금.']];
allocation.getRange(`A${metricsRow+7}`).values=[['변동성은 과거 가격의 추정치이며 최대 손실이나 미래 위험을 뜻하지 않음.']];

const n=predict.rankings.length;
base(ranking,`A1:H${n+6}`,[10,12,44,14,14,15,25,22]);
title(ranking,'S&P 500 전체 종목 순위');
ranking.getRange('A3').values=[[`${audit.universe_count}개 구성 종목 중 ${n}개 산출. 독립 분석은 상위 30개만 수행.`]];
ranking.getRange('A4').values=[['재무 원천: Yahoo Finance 현재 스냅샷. https://finance.yahoo.com/']];
ranking.getRange('A5').values=[['P/E는 후행 값 우선, 없으면 선행 값 대체. 상위 후보 IVZ는 선행 P/E.']];
header(ranking,6,['순위','티커','회사','순위 점수','P/E','ROE (%)','섹터','검토 결과']);
const excluded=new Map(audit.excluded.map(r=>[r.ticker,r.exclusion_reason]));
ranking.getRange(`A7:H${n+6}`).values=predict.rankings.map((r,i)=>[r.rank,r.ticker,r.company_name,r.total_score,r.metrics?.pe??'n.a.',r.metrics?.roe??'n.a.',r.metrics?.sector??'Unknown',portfolio.weights[r.ticker]?'편입':i<30?'제외':'순위만 산출']);
ranking.getRange(`D7:F${n+6}`).setNumberFormat('0.00');
ranking.getRange(`D7:F${n+6}`).format.horizontalAlignment='right';
stripe(ranking,7,n,8);
ranking.freezePanes.freezeRows(6);
ranking.tables.add(`A6:H${n+6}`,true,'RankingTable');

const analysisRows=[];
for (const r of predict.rankings.slice(0,30)) for(const i of ['buffett','lynch','fisher']) {
  const a=investor.analyses[r.ticker][i];
  analysisRows.push([r.ticker,names[i],signals[a.signal],a.confidence,a.data_quality,a.reasoning]);
}
base(detail,`A1:F${analysisRows.length+6}`,[11,11,11,12,14,115]);
title(detail,'독립 투자자 분석 90건');
detail.getRange('A3').values=[['투자 철학을 적용한 LLM 판단. 투자자 본인의 실제 의견이나 성공 확률이 아님.']];
detail.getRange('A4').values=[['원천: Yahoo Finance 현재 재무 스냅샷과 연간 재무제표. https://finance.yahoo.com/']];
header(detail,6,['티커','관점','판단','신뢰도 /100','자료 품질','판단 근거와 한계']);
detail.getRange(`A7:F${analysisRows.length+6}`).values=analysisRows;
detail.getRange(`A7:F${analysisRows.length+6}`).format.rowHeight=125;
detail.getRange(`F7:F${analysisRows.length+6}`).format.wrapText=true;
detail.getRange(`F7:F${analysisRows.length+6}`).format.verticalAlignment='top';
stripe(detail,7,analysisRows.length,6);
detail.freezePanes.freezeRows(6);

base(evidence,'A1:F85',[32,25,15,31,27,18]);
title(evidence,'위험과 데이터 근거');
evidence.getRange('A3').values=[[`분석일 ${portfolio.analysis_date}. 현재 스냅샷이며 과거 시점 재현이나 OOS 성과 검증이 아님.`]];
header(evidence,5,['시장 지표','값']);
const regime=risk.market_regime;
const marketRows=[['벤치마크',regime.benchmark],['가격 기준일',regime.as_of_date],['가격 규칙 기반 국면',regime.regime],['시장 목표 현금',regime.target_cash_weight],['SPY 종가 (USD)',regime.metrics.close],['200일선 이격',regime.metrics.distance_to_sma_200],['6개월 모멘텀',regime.metrics.momentum_126],['14일 RSI',regime.metrics.rsi_14],['252일 고점 대비',regime.metrics.drawdown_from_252d_peak],['20일 실현 연변동성',regime.metrics.realized_volatility_20]];
evidence.getRange('A6:B15').values=marketRows;
for(const r of [9,11,12,14,15]) evidence.getRange(`B${r}`).setNumberFormat(percent);
for(const r of [10,13]) evidence.getRange(`B${r}`).setNumberFormat('0.00');
header(evidence,18,['섹터','비중']);
const sectors=Object.entries(audit.sector_weights).sort((a,b)=>b[1]-a[1]);
evidence.getRangeByIndexes(18,0,sectors.length,2).values=sectors;
evidence.getRange(`B19:B${18+sectors.length}`).setNumberFormat(percent);
header(evidence,31,['제외 종목','제외 이유']);
const exRows=audit.excluded.map(r=>[r.ticker,r.exclusion_reason]);
evidence.getRangeByIndexes(31,0,exRows.length,2).values=exRows;
evidence.getRange('B1:B85').format.columnWidth=85;
const notesRow=Math.max(50,34+exRows.length);
const notes=[
 ['직접 관찰',`구성 ${audit.universe_count}개, 순위 ${n}개, 독립 분석 ${analysisRows.length}건. 비중 제약 검증 통과.`],
 ['외부 출처','Yahoo Finance: 가격·현재 재무자료. https://finance.yahoo.com/'],
 ['외부 출처','S&P 500 구성 목록: https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'],
 ['외부 출처','SPY 보유 목록(2026-09-04)과 503개 일치. https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy'],
 ['대체 조회','Wikipedia 최초 직접 감사 403. HTTP 응답을 표로 읽는 방식으로 복구. 과거 구성 근거는 아님.'],
 ['추론','순위, 투자자 판단, 시장 국면, 목표 현금은 휴리스틱. 신뢰도는 미래 성공 확률이 아님.'],
 ['미검증','정확히 같은 파이프라인의 point-in-time/OOS 성과, 전 종목 공시 원문 대조, 완전한 뉴스 검토.'],
 ['위험 범위','USD 기준. 세금·환율 변동·수수료·체결 슬리피지 제외. 현금의 변동성은 0으로 가정.'],
 ['시점','재무제표 결산일과 조회일은 다름. Yahoo 수정 이력 및 당시 공시 가용성은 검증하지 않음.'],
 ['CF 공식 발표','현재 FCF와 회사 정의 FCF 차이 미조정. https://www.cfindustries.com/newsroom/2026/1h-2026-earnings'],
 ['PSX 공식 발표','운전자본 영향을 포함하는 OCF와 제외 수치 구분. https://investor.phillips66.com/financial-information/news-releases/news-release-details/2026/Phillips-66-Delivers-Strong-Second-Quarter-Results-and-Operating-Performance/default.aspx'],
 ['MU 공식 발표','Yahoo FCF와 회사 분기 조정 FCF는 정의·기간 차이 미조정. https://investors.micron.com/news/press-release/2026/Micron-Technology-Inc--Reports-Record-Results-for-the-Third-Quarter-of-Fiscal-2026/default.aspx']
];
evidence.getRangeByIndexes(notesRow-1,0,notes.length,2).values=notes;
evidence.getRangeByIndexes(notesRow-1,1,notes.length,1).format.wrapText=true;
evidence.getRangeByIndexes(notesRow-1,0,notes.length,2).format.rowHeight=56;
evidence.freezePanes.freezeRows(5);

wb.recalculate();
const total=allocation.getRange(`D${totalRow}`).values[0][0];
if(Math.abs(total-1)>1e-9) throw new Error(`Allocation total ${total}`);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:2000})).ndjson);
for (const [sheetName,range,file] of [['포트폴리오',`A1:G${totalRow+12}`,'allocation'],['전체 순위','A1:H18','rankings'],['독립 투자자 분석','A1:F10','investors'],['위험과 근거','A1:B29','risk'],['위험과 근거',`A${notesRow}:B${notesRow+notes.length-1}`,'evidence']]) {
  const blob=await wb.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(path.join(outputDir,`${file}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const result=await SpreadsheetFile.exportXlsx(wb);
const output=path.join(outputDir,'sp500_20260909_portfolio.xlsx');
await result.save(output);
console.log(JSON.stringify({output,sheets:4,independentAnalyses:analysisRows.length,rankingRows:n,total}));
