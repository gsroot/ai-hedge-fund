import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const dir = path.dirname(fileURLToPath(import.meta.url));
const report = JSON.parse(await fs.readFile(path.join(dir, 'report_details.json'), 'utf8'));
const sources = JSON.parse(await fs.readFile(path.join(dir, 'investor_source_data.json'), 'utf8')).stocks;
const wb = Workbook.create();
const sheets = ['포트폴리오', '후보 비교', '투자자 근거', '재무 입력'].map(name => wb.worksheets.add(name));
const [main, candidates, opinions, inputs] = sheets;
const colors = {dark:'#193747', teal:'#176B74', light:'#EAF1F4', muted:'#556973'};
const txtSignal = {bullish:'긍정', neutral:'유보', bearish:'부정'};

function base(sheet, lastCol, lastRow) {
  sheet.showGridLines = false;
  const range = sheet.getRange(`A1:${lastCol}${lastRow}`);
  range.format.font = {name:'Malgun Gothic', size:10, color:'#152D3A'};
  range.format.rowHeight = 24;
  range.format.verticalAlignment = 'center';
  range.format.columnWidth = 15;
}
function title(sheet, text) {
  sheet.getRange('A2').values = [[text]];
  sheet.getRange('A2').format.font = {name:'Malgun Gothic', size:16, bold:true, color:colors.dark};
  sheet.getRange('A2').format.rowHeight = 30;
}
function head(sheet, range, values) {
  const r = sheet.getRange(range);
  r.values = [values];
  r.format.fill = colors.dark;
  r.format.font = {name:'Malgun Gothic', size:10, color:'#FFFFFF', bold:true};
  r.format.horizontalAlignment = 'center';
  r.format.rowHeight = 30;
}
function stripes(sheet, from, to, end) {
  for(let r=from;r<=to;r++) if((r-from)%2===1) sheet.getRange(`A${r}:${end}${r}`).format.fill = '#F3F6F8';
}
const reasons = {'003230':'반기 매출 성장과 투자 후 현금 회복', '062040':'매출·마진 성장과 낮은 부채 비율', '214450':'높은 수익성과 3개 관점 긍정', '483650':'반기 성장·현금 전환과 3개 관점 긍정', '326030':'흑자 전환 후 성장과 현금 창출'};
const stockRows = report.included.map(r=>[r.ticker,r.company_name,r.weight/100,r.sector,r.combined_confidence/100,r.annualized_volatility,`${r.bullish_count}/3`,reasons[r.ticker]]);
const start=13, last=start+stockRows.length-1, cashRow=last+1, totalRow=cashRow+1;
const sectorEntries = [...new Set(report.included.map(r=>r.sector))].sort();
base(main,'H',totalRow+sectorEntries.length+8);
main.tabColor=colors.dark;
title(main,'KRX 연구 포트폴리오');
main.getRange('A4').values=[['분석·종목 가격 2026-09-09. 시가총액·유니버스·시장 벤치마크 2026-09-08.']];
main.getRange('A5').values=[['KOSPI 시총 상위 200개 + KOSDAQ 시총 상위 150개 대체 유니버스. 정식 지수 구성종목과 다름.']];
main.getRange('A6').values=[['팩터 prior_only. 전체 파이프라인 OOS 미검증. 뉴스는 위험·설명 전용. confidence는 성공 확률이 아님.']];
main.getRange('A4:H6').format.font={name:'Malgun Gothic',size:10,color:colors.muted};
main.getRange('A10').values=[['5종목 모두 15% 상한에 도달해 실제 현금은 25%. 종목별 위험이 같다는 뜻은 아니다.']];
main.getRange('A8').values=[['주식 비중']]; main.getRange('B8').formulas=[[stockRows.length ? `=SUM(C${start}:C${last})` : '=0']];
main.getRange('D8').values=[['현금 비중']]; main.getRange('E8').formulas=[[`=C${cashRow}`]];
main.getRange('G8').values=[['시장 현금 목표']];main.getRange('H8').values=[[report.market_regime.target_cash_weight]];
for(const a of ['B8','E8','H8'])main.getRange(a).setNumberFormat('0.0%');
head(main,'A12:H12',['종목코드','종목명','비중','섹터','합의 신뢰도','연환산 변동성','긍정 관점 수','편입 근거']);
if(stockRows.length)main.getRange(`A${start}:H${last}`).values=stockRows;
main.getRange(`A${cashRow}:H${cashRow}`).values=[['CASH','현금',report.cash_weight/100,'현금',null,null,null,'시장 목표와 종목·섹터 제약 반영']];
main.getRange(`B${totalRow}`).values=[['합계']];main.getRange(`C${totalRow}`).formulas=[[`=SUM(C${start}:C${cashRow})`]];
main.getRange(`A${totalRow}:H${totalRow}`).format.fill=colors.light;
main.getRange(`C${start}:C${totalRow}`).setNumberFormat('0.0%');
main.getRange(`E${start}:F${last >= start ? last : start}`).setNumberFormat('0.0%');
main.getRange(`H${start}:H${cashRow}`).format.wrapText=true;
main.getRange('A1:A60').format.columnWidth=12;
main.getRange('B1:B60').format.columnWidth=23;
main.getRange('D1:D60').format.columnWidth=22;
main.getRange('H1:H60').format.columnWidth=51;
stripes(main,start,cashRow,'H');
const sectorStart=totalRow+4;
head(main,`B${sectorStart}:D${sectorStart}`,['섹터','한도','배분 비중']);
sectorEntries.forEach((sector,i)=>{
  const r=sectorStart+1+i;
  main.getRange(`B${r}:C${r}`).values=[[sector,0.35]];
  main.getRange(`D${r}`).formulas=[[`=SUMIFS($C$${start}:$C$${last},$D$${start}:$D$${last},B${r})`]];
});
main.getRange(`C${sectorStart+1}:D${sectorStart+Math.max(sectorEntries.length,1)}`).setNumberFormat('0.0%');

base(candidates,'I',report.top_stocks.length+8);title(candidates,'상위 30개 후보 비교');
candidates.getRange('A4').values=[['연구점수는 기대수익률이 아니다. 긍정 관점 과반, 필수 데이터, 변동성·상관, 비중 제약을 적용했다.']];
head(candidates,'A6:I6',['종목코드','종목명','연구점수','섹터','버핏','린치','피셔','편입 비중','제외 사유']);
const includedMap=new Map(report.included.map(r=>[r.ticker,r]));
const excludedMap=new Map(report.excluded.map(r=>[r.ticker,r.exclusion_reason]));
const candidateRows=report.top_stocks.map(r=>[r.ticker,r.company_name,r.total_score,r.sector,...['buffett','lynch','fisher'].map(i=>txtSignal[r.investor_analysis[i].signal]),(includedMap.get(r.ticker)?.weight??0)/100,excludedMap.get(r.ticker)??'']);
candidates.getRange(`A7:I${6+candidateRows.length}`).values=candidateRows;
candidates.getRange(`C7:C${6+candidateRows.length}`).setNumberFormat('0.00');
candidates.getRange(`H7:H${6+candidateRows.length}`).setNumberFormat('0.0%');
candidates.getRange('B1:B40').format.columnWidth=23;candidates.getRange('D1:D40').format.columnWidth=22;
candidates.getRange('I1:I40').format.columnWidth=58;candidates.getRange('I7:I36').format.wrapText=true;
candidates.getRange('A7:I36').format.rowHeight=34;stripes(candidates,7,36,'I');candidates.freezePanes.freezeRows(6);

const opinionRows=[];
for(const r of report.top_stocks)for(const inv of ['buffett','lynch','fisher']){
  const a=r.investor_analysis[inv], s=sources[r.ticker];
  opinionRows.push([r.ticker,r.company_name,{buffett:'버핏',lynch:'린치',fisher:'피셔'}[inv],txtSignal[a.signal],a.confidence/100,a.data_quality,a.reasoning,[s.statements.annual_2025.source_urls?.[0],s.statements.half_year_2026.source_urls?.[0]].filter(Boolean).join('\n')]);
}
base(opinions,'H',opinionRows.length+8);title(opinions,'독립 투자자 분석 근거');
opinions.getRange('A4').values=[['같은 원자료를 각 관점에서 독립 평가했다. confidence는 모델 판단 강도이며 확률로 보정하지 않았다.']];
head(opinions,'A6:H6',['종목코드','종목명','관점','판단','confidence','자료 상태','독립 판단 근거','원문 출처']);
opinions.getRange(`A7:H${6+opinionRows.length}`).values=opinionRows;
opinions.getRange(`E7:E${6+opinionRows.length}`).setNumberFormat('0%');
opinions.getRange('B1:B100').format.columnWidth=23;opinions.getRange('G1:G100').format.columnWidth=100;opinions.getRange('H1:H100').format.columnWidth=66;
opinions.getRange(`G7:H${6+opinionRows.length}`).format.wrapText=true;
for(let i=0;i<opinionRows.length;i++)opinions.getRange(`A${i+7}:H${i+7}`).format.rowHeight=Math.max(70,Math.ceil(opinionRows[i][6].length/57)*16+12);
stripes(opinions,7,6+opinionRows.length,'H');opinions.freezePanes.freezeRows(6);

base(inputs,'M',37);title(inputs,'재무 입력과 출처');
inputs.getRange('A4').values=[['금액은 십억원(KRW). 연결 우선·별도 대체. 2025 연간 공시 수치와 현재 PER은 기간이 서로 다를 수 있다.']];
inputs.getRange('A5').values=[['n.a.는 누락 또는 모호한 계정이다. FCF는 CFO에서 유형·무형자산 취득액을 차감한 단순 계산이다.']];
inputs.getRange('A6').values=[['지주·보험회사의 이익률은 일반기업과 직접 비교 불가. 반기 공시 링크는 투자자 근거 시트에 수록.']];
head(inputs,'A7:M7',['종목코드','종목명','PER','PBR','2025 매출','영업이익률','CFO','FCF','2026H1 매출','H1 영업이익률','회계 기준','DART 공시','밸류에이션']);
const num=v=>typeof v==='number'?v:'n.a.';
const amount=v=>typeof v==='number'?v/1e9:'n.a.';
const inputRows=report.top_stocks.map(r=>{
  const s=sources[r.ticker],a=s.statements.annual_2025,h=s.statements.half_year_2026, av=a.periods?.['2025']??{},hv=h.periods?.['2026H1']??{};
  return [r.ticker,r.company_name,num(s.metrics.price_to_earnings_ratio),num(s.metrics.price_to_book_ratio),amount(av.revenue),num(av.operating_margin),amount(av.operating_cash_flow),amount(av.fcf_after_ppe_and_intangibles),amount(hv.revenue),num(hv.operating_margin),a.fs_div??'n.a.',a.source_urls?.[0]??'n.a.',s.valuation_source_url];
});
inputs.getRange(`A8:M${7+inputRows.length}`).values=inputRows;
inputs.getRange('B1:B40').format.columnWidth=23;inputs.getRange('L1:M40').format.columnWidth=66;
inputs.getRange('C8:E37').setNumberFormat('#,##0.00;(#,##0.00);"-"');inputs.getRange('G8:I37').setNumberFormat('#,##0.0;(#,##0.0);"-"');
for(const col of ['F','J'])inputs.getRange(`${col}8:${col}37`).setNumberFormat('0.0%');
inputs.getRange('A8:M37').format.rowHeight=32;stripes(inputs,8,37,'M');inputs.freezePanes.freezeRows(7);
// Keep the original six-character strings; explicit display also preserves zeros in the renderer.
for (const sheet of sheets) sheet.getRange('A1:A100').setNumberFormat('000000');
wb.recalculate();
const total=main.getRange(`C${totalRow}`).values[0][0];
if(Math.abs(total-1)>1e-6)throw new Error(`Portfolio total ${total}`);
const inspections=[];
inspections.push((await wb.inspect({kind:'table',range:`포트폴리오!A8:H${totalRow}`,include:'values,formulas',tableMaxRows:35,tableMaxCols:8,maxChars:5500})).ndjson);
inspections.push((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'formula error scan'})).ndjson);
await fs.writeFile(path.join(dir,'workbook_verification.txt'),inspections.join('\n'));
for(const [sheet,range,name] of [[main,`A1:H${sectorStart+sectorEntries.length}`,'portfolio'],[candidates,'A1:I16','candidates'],[opinions,'A1:H12','opinions'],[inputs,'A1:M16','inputs']]){
  const preview=await wb.render({sheetName:sheet.name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(dir,`preview_${name}.png`),new Uint8Array(await preview.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(dir,'KRX_연구포트폴리오_20260909.xlsx'));
console.log(JSON.stringify({worksheets:sheets.length,portfolio_total:total,stocks:report.included.length,independent_opinions:opinionRows.length}));
