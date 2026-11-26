"""Card matching, validation and template filling. No game I/O in this module."""
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ORDER = ('DH','C','1B','2B','3B','SS','LF','CF','RF')
STAT_KEYS = {'파워':'POWER','정확':'CONTACT','선구':'VISION','인내':'DISCIPLINE','주루':'RUNNING_SPEED','수비':'FIELDING'}
KINDS = {0:'라올',1:'임팩',2:'시그',3:'시즌',4:'골글',5:'국대',6:'라올'}
KIND_LABELS = {0:'라이브',1:'임팩트',2:'시그니처',3:'시즌',4:'골든글러브',5:'국가대표',6:'라이브 올스타'}
PICKER_KINDS = {'임팩트':1,'시그':2,'시즌':3,'라이브':0,'올스타':6,'국대':5,'골글':4}
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('',NS)

def compact(text):
    return re.sub(r'\s+', '', text or '')

def fa_status(record):
    """FA is optional manual metadata, never inferred from table shape or signs."""
    override=record.get('fa_override')
    if type(override) is bool:return 'FA' if override else '일반'
    return '일반'

def compare_base_values(base,card):
    return [{'stat':stat,'screen':base.get(stat),'database':card.get('stats',{}).get(key),
             'status':'unreadable' if type(base.get(stat)) is not int else
                      'match' if base[stat]==card.get('stats',{}).get(key) else 'mismatch'}
            for stat,key in STAT_KEYS.items()]

class CardDatabase:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self.cards = [c for c in json.loads(Path(path).read_text(encoding='utf-8-sig')) if c.get('role')=='타자']
        self.names = sorted({c.get('player') or re.sub(r"['’]\d+$",'',c['name']) for c in self.cards},key=len,reverse=True)
        self.by_id={c['id']:c for c in self.cards}
        concepts=Path(__file__).parent/'impact-concepts.json'
        self.impact_concepts=json.loads(concepts.read_text(encoding='utf-8')) if concepts.exists() else {}

    def entry(self,card,base=None):
        base=base or {}
        result={k:card.get(k) for k in ['id','name','player','season','kind','stats','template','team','active','grade','stars','position','impact_category']}
        result['stars']=card.get('stars',card.get('grade'))
        result['impact_concept']=(card.get('impact_concept') or self.impact_concepts.get(str(card.get('impact_category')),f'컨셉 {card.get("impact_category")}')) if card.get('kind')==1 else ''
        result['kind_label']=KIND_LABELS.get(card.get('kind'),'미분류')
        result['base_comparison']=compare_base_values(base,card)
        result['differences']={k:{'screen':base[k],'database':card['stats'].get(v)} for k,v in STAT_KEYS.items() if type(base.get(k)) is int and base[k]!=card['stats'].get(v)}
        return result

    def catalog(self,name='',stars=None,kind=None,season=None,base=None,impact_category=None):
        """Browse saved cards even if OCR did not identify any player name."""
        query=compact(name).casefold();cards=[]
        for card in self.cards:
            if stars is not None and card.get('stars',card.get('grade'))!=int(stars):continue
            if kind is not None and card.get('kind')!=int(kind):continue
            if impact_category is not None and (card.get('kind')!=1 or card.get('impact_category')!=int(impact_category)):continue
            year=card.get('season')
            if season=='연도 없음':
                if type(year) is int and 1900<=year<=2100:continue
            elif season is not None and year!=int(season):continue
            if query and not any(query in compact(value).casefold() for value in [card.get('player'),card.get('name')]):continue
            cards.append(self.entry(card,base))
        return sorted(cards,key=lambda c:(len(c['differences']),not bool(c.get('active')),c['name'],c['id']))

    def choose_id(self,table,card_id,confirm_mismatch=False):
        """Explicit catalogue selection may correct an unreadable or wrong OCR name."""
        card=self.by_id.get(int(card_id))
        if card is None:raise ValueError('선택한 카드가 현재 카드 JSON에 없습니다.')
        entry=self.entry(card,table.get('기본',{}))
        complete=all(type(table.get('기본',{}).get(k)) is int for k in STAT_KEYS)
        if not complete or entry['differences']:
            if not confirm_mismatch:raise ValueError('기본값 누락/불일치 내용을 확인한 뒤 선택하세요.')
            status='manual_selected'
        else:status='verified'
        return {'status':status,'card':entry,'candidates':[entry],'manual_selection':True,
                'selection_source':'catalog','message':'저장된 카드 목록에서 사용자가 선택 (추출 능력치는 유지)'}

    def visible_names(self, text):
        text=compact(text)
        return [name for name in self.names if compact(name) in text]

    def by_name(self,name,base=None):
        name=compact(name);base=base or {}
        cards=[]
        for c in self.cards:
            player=c.get('player') or re.sub(r"['’]\d+$",'',c['name'])
            # Display names can omit the B/S suffix used to disambiguate same-name players.
            if name not in (compact(player),compact(c['name']),re.sub(r'[A-Z]$','',compact(player))):continue
            cards.append(self.entry(c,base))
        return sorted(cards,key=lambda c:(len(c['differences']),not bool(c.get('active')),c.get('kind') or 0,c.get('season') or 0,c['id']))

    def choose(self,table,observed_text,card_id,confirm_mismatch=False,search_name=None):
        names=[search_name] if search_name else self.visible_names(observed_text)
        candidates={c['id']:c for n in names for c in self.by_name(n,table['기본'])}
        card=candidates.get(int(card_id))
        if card is None:raise ValueError('조회한 선수명 후보에서 카드를 선택하세요.')
        complete=all(type(table['기본'].get(k)) is int for k in STAT_KEYS)
        if not complete or card['differences']:
            if not confirm_mismatch:raise ValueError('기본값 누락/불일치가 있습니다. 차이를 확인하고 명시적으로 선택해야 합니다.')
            status='manual_selected'
        else:status='verified'
        return {'status':status,'card':card,'candidates':list(candidates.values()),'manual_selection':True,'message':'사용자가 선수명 후보에서 직접 선택 (추출 능력치는 변경하지 않음)'}

    def match(self, table, observed_text=''):
        base=table['기본']
        observed_names=self.visible_names(observed_text)
        name_candidates={c['id']:c for name in observed_names for c in self.by_name(name,base)}
        if any(type(base.get(k)) is not int for k in STAT_KEYS):
            return {'status':'unreadable_base','candidates':list(name_candidates.values()),'message':'기본값 미인식. 선수명 후보에서 직접 선택할 수 있습니다. DB 값으로 자동 보정하지 않습니다.'}
        pool=[c for c in self.cards if all(c.get('stats',{}).get(v)==base[k] for k,v in STAT_KEYS.items())]
        # Six stats and OCR identity must agree; numerical coincidence alone is not identity.
        if observed_names:
            pool=[c for c in pool if c.get('player') in observed_names]
        candidates=[{'id':c['id'],'name':c['name'],'player':c.get('player'),'season':c.get('season'),'kind':c.get('kind'),'stats':c['stats'],'template':c.get('template')} for c in pool]
        if not observed_names:
            return {'status':'identity_unreadable','candidates':candidates,'message':'선수명 미인식. 스탯이 같아도 자동 확정하지 않음.'}
        if len(pool)==1:
            return {'status':'verified','candidates':candidates,'card':candidates[0],'message':'선수명 + 기본 6개 모두 일치'}
        if len(pool)>1:
            return {'status':'ambiguous','candidates':candidates,'message':'같은 기본값의 카드가 여러 개. 카드 ID 직접 선택 필요.'}
        nearest=[]
        for c in self.cards:
            if c.get('player') not in observed_names: continue
            diffs={k:{'screen':base[k],'database':c.get('stats',{}).get(v)} for k,v in STAT_KEYS.items() if base[k]!=c.get('stats',{}).get(v)}
            nearest.append({'id':c['id'],'name':c['name'],'differences':diffs})
        nearest.sort(key=lambda c:len(c['differences']))
        return {'status':'mismatch','candidates':list(name_candidates.values()),'nearest':nearest[:5],'message':'기본 능력치 불일치. 같은 이름의 모든 카드 중 직접 선택할 수 있습니다.'}

def validate_table(table):
    issues=[]
    for row,values in table.items():
        for stat in STAT_KEYS:
            if type(values.get(stat)) is not int: issues.append(f'{row}/{stat}: 숫자 미인식')
    for stat in STAT_KEYS:
        values=[v.get(stat) for v in table.values()]
        if all(type(v) is int for v in values):
            total=sum(v[stat] for k,v in table.items() if k!='종합')
            if total!=table['종합'][stat]: issues.append(f'{stat}: 보정합 {total} / 종합 {table["종합"][stat]} 불일치')
    return issues

def export_issues(records):
    issues=[]
    if [r['slot'] for r in records]!=list(ORDER): issues.append('DH부터 RF까지 9명 필요')
    names=[]
    for r in records:
        # The website recalculates totals. Export raw basic/training/spec values only.
        # FA and deck/synergy rows must never be merged into these values or gate export.
        for row in ['기본','훈련','특훈']:
            for stat in list(STAT_KEYS)[:4]:
                if type(r['stats']['table'].get(row,{}).get(stat)) is not int:
                    issues.append(f'{r["slot"]}: {row}/{stat} 입력 필요')
        if r['match']['status']!='verified' and not (r['match']['status']=='manual_selected' and r['match'].get('manual_selection')): issues.append(f'{r["slot"]}: 카드 검증 미완료')
        card=r['match'].get('card',{})
        names.append(sheet_player_name(card))
        if card.get('kind')==3: issues.append(f'{r["slot"]}: 사이트 시트 가져오기는 시즌 종류 코드를 지원하지 않음')
        if not re.fullmatch(r'\d+(강|각성)',r.get('enhance','')): issues.append(f'{r["slot"]}: 강화/각성 단계 입력 필요 (예: 0강)')
        pending=r.get('skill_capture',{}).get('unresolved',[])
        for index in pending:issues.append(f'{r["slot"]}: 스킬 {index+1} 인식 결과를 선수 수정에서 확인하세요.')
        for index,skill in enumerate(r.get('skills',[])[:3],1):
            if not skill:continue
            name=skill.get('name');level=skill.get('lv')
            if not name and level is None:continue
            if not isinstance(name,str) or not name.strip():issues.append(f'{r["slot"]}: 스킬 {index} 이름 입력 필요')
            if type(level) is not int or not 1<=level<=99:issues.append(f'{r["slot"]}: 스킬 {index} 레벨은 숫자로 입력하세요.')
    if len(names)!=len(set(names)): issues.append('동일 선수명이 중복됨. 사이트는 라인업을 이름으로 연결하므로 직접 검토 필요')
    return issues

def sheet_player_name(card):
    # Keep disambiguating B/S suffixes. Two different 이재원 cards must not collapse to one name.
    return re.sub(r"['’]\d{2,4}$",'',card.get('name') or card.get('player') or '').strip()

def _column(index):
    out=''
    while index:
        index,k=divmod(index-1,26);out=chr(65+k)+out
    return out


def sheet_awakening_potential(value):
    # The website maps a literal '-' to C and then enables 뜬공형. A missing
    # awakening must therefore be an empty cell, while the raw UI/JSON stays '-'.
    text='' if value is None else str(value).strip()
    return None if text in ('','-','0') else text

def fill_template(template, output, records):
    issues=export_issues(records)
    if issues: raise ValueError('\n'.join(issues))
    values={}
    for i,r in enumerate(records):
        card=r['match']['card'];t=r['stats']['table'];row=8+i
        season=card.get('season')
        # Preserve real years; internal Impact sentinel (3000) is not a calendar year.
        is_fa=fa_status(r)=='FA'
        name=sheet_player_name(card)
        data=[None,KINDS[card['kind']]+('(F)' if is_fa else ''),name,season if isinstance(season,int) and 1900<=season<=2100 else None,r['slot'],r['enhance'],r.get('pot1') or '-',r.get('pot2') or '-',sheet_awakening_potential(r.get('pot3'))]
        for stat in list(STAT_KEYS)[:4]: data += [t['기본'][stat],t['훈련'][stat],t['특훈'][stat]]
        for col,value in enumerate(data,1): values[f'{_column(col)}{row}']=value
        overview=r.get('overview',{})
        # Optional fields are written when reviewed; missing observations are not fabricated.
        for col,value in [('V',r.get('hand',overview.get('hand'))),('W',overview.get('launch_angle')),('X',r.get('white_zone')),('Y',r.get('cold_zone'))]:values[f'{col}{row}']=value
        skills=r.get('skills',[])
        for index,(namecol,levelcol) in enumerate([('Z','AA'),('AB','AC'),('AD','AE')]):
            skill=skills[index] if index<len(skills) and skills[index] else {}
            values[f'{namecol}{row}']=skill.get('name');values[f'{levelcol}{row}']=skill.get('lv')
        # Batting order is a separate user input; never derive it from scan order.
        lr=79+i
        for col,value in [('D',r.get('batting_order')),('E',r['slot']),('I',name)]: values[f'{col}{lr}']=value
    orders=[r.get('batting_order') for r in records]
    if sorted(v for v in orders if type(v) is int)!=list(range(1,10)):
        raise ValueError('타순 1~9를 중복 없이 입력해야 라인업을 내보낼 수 있습니다.')
    with zipfile.ZipFile(template) as src:
        root=ET.fromstring(src.read('xl/worksheets/sheet1.xml'))
        data=root.find(f'{{{NS}}}sheetData')
        for address,value in values.items():
            rn=int(re.search(r'\d+',address)[0]);row=data.find(f'{{{NS}}}row[@r="{rn}"]')
            if row is None: row=ET.SubElement(data,f'{{{NS}}}row',{'r':str(rn)})
            cell=row.find(f'{{{NS}}}c[@r="{address}"]')
            if cell is None: cell=ET.SubElement(row,f'{{{NS}}}c',{'r':address})
            for child in list(cell):cell.remove(child)
            cell.attrib.pop('t',None)
            if value is None: continue
            if type(value) is int: ET.SubElement(cell,f'{{{NS}}}v').text=str(value)
            else:
                cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,f'{{{NS}}}is'),f'{{{NS}}}t').text=str(value)
        # XML cells must stay in ascending column order.
        def col_index(c):
            n=0
            for ch in re.match(r'[A-Z]+',c.get('r'))[0]:n=n*26+ord(ch)-64
            return n
        for row in data:
            children=sorted(list(row),key=col_index)
            row[:]=children
        data[:]=sorted(list(data),key=lambda row:int(row.get('r')))
        payload=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as dst:
            for entry in src.infolist():dst.writestr(entry,payload if entry.filename=='xl/worksheets/sheet1.xml' else src.read(entry.filename))
