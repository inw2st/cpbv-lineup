"""Pure presentation status helpers; no Tk dependency in the new desktop app."""

def potential_confirmed(record,key):
    observed=record.get('potentials',{}).get(key,{})
    value=record.get(key)
    return bool(value and value!='-') or observed.get('status')=='not_present'


def skills_confirmed(record):
    pending=record.get('skill_capture',{}).get('unresolved',[])
    return sum(i not in pending and bool(s and s.get('name') and type(s.get('lv')) is int)
               for i,s in enumerate(record.get('skills',[])[:3]))


def review_count(record):
    issues={s for s in record.get('issues',[]) if s not in ('OVR 확인 필요','오버롤 확인 필요')}
    status=record.get('match',{}).get('status')
    if status not in ('verified','manual_selected'):issues.add('카드 연결')
    if not record.get('enhance'):issues.add('강화·각성')
    if record.get('batting_order') not in range(1,10):issues.add('타순')
    if not all(potential_confirmed(record,k) for k in ('pot1','pot2','pot3')):issues.add('잠재력')
    if skills_confirmed(record)<3:issues.add('스킬')
    return len(issues)
