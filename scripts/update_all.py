"""서울25구+경기5시를 검증한 뒤 한 번에 발행. 실패하면 공개된 HTML/JSON 유지."""
import collections,copy,json,os,shutil,tempfile
from pathlib import Path
from pipeline import DataError,read_json,atomic_json,now,last_closed_month,validate_dataset
from seoul_public import run_public
from kapt_public import download_kapt,normalize_gyeonggi,gyeonggi_region_tags
from gyeonggi_public import CITIES,VIEW,PublicClient,query_plan,download_responses,collect
from embed_data import embedded_html
from dataset_storage import publish_bundle

def merge_data(seoul,gg,report,kapt_report,held):
    d=copy.deepcopy(seoul)
    for c in gg:c['region_tags']=gyeonggi_region_tags(c)
    d['complexes'].extend(gg);d['complexes'].sort(key=lambda c:(c['region'],c['id']))
    cities=[x for x in CITIES if any(c['region']==x for c in gg)]+sorted({c['region'] for c in gg}-set(CITIES))
    m=d['meta'];m.update(provider='seoul_gyeonggi_official',loaded_regions=m['loaded_regions']+cities,complex_count=len(d['complexes']),scope_label=f'서울 25구 · 경기 {len(cities)}시',updated_at=now(),gyeonggi_regions=cities,source_verified=True)
    m['available_region_filters']=list(dict.fromkeys(m['loaded_regions']+[tag for c in gg for tag in c['region_tags']]))
    m['sources'].update(gyeonggi=VIEW,kapt='https://www.data.go.kr/data/15073271/fileData.do');m['kapt_metadata_download']=kapt_report
    m['jeonse_rows']=sum(len(c.get('jeonse_tx',[])) for c in d['complexes']);m['far_verified_count']=sum((c.get('far_info') or {}).get('status')=='verified' for c in d['complexes'])
    m['region_feature_counts'].update({city:{'far_verified':0,'jeonse_rows':sum(len(c.get('jeonse_tx',[])) for c in gg if c['region']==city),'new_renewal_classification':False} for city in cities})
    m['catalog_exclusions']=m.get('catalog_exclusions',[])+held
    m['note']='서울 25구·성남·과천·안양·화성·광명. 300세대 이상·분양/혼합 단지. 경기 용적률과 전세 신규/갱신 구분 미확인. 합산 관리단지 세대수 충돌 보류.'
    validate_dataset(d)
    report['unresolved_complexes']=[x for x in report.get('unresolved_complexes',[]) if x.get('region') in seoul['meta']['loaded_regions']]+report.get('gyeonggi',{}).get('unresolved_complexes',[])
    report['complex_count']=len(d['complexes']);report['trade_count']=sum(len(c['tx']) for c in d['complexes']);report['jeonse_rows']=m['jeonse_rows'];report['region_complex_counts']=dict(collections.Counter(c['region'] for c in d['complexes']));report['region_trade_counts']={r:sum(len(c['tx']) for c in d['complexes'] if c['region']==r) for r in m['loaded_regions']};report['catalog_exclusions']=m['catalog_exclusions'];report['gyeonggi_source_note']=m['note']
    return d,report

def run_all(root):
    root=Path(root);old=read_json(root/'data/site-data.json');settings=read_json(root/'config/settings.json')
    try:
        rows,kapt_report=download_kapt();cat,held=normalize_gyeonggi(rows,settings.get('gyeonggi_cities',CITIES),old.get('complexes',[]))
        client=PublicClient();plan,uncovered=query_plan(cat,client)
        responses=download_responses(plan,settings['start_month'],last_closed_month())
        gg,gg_report=collect(cat,responses,plan,settings['start_month'],last_closed_month(),old.get('complexes',[]));gg_report['unresolved_address_ids']=uncovered;gg_report['source_hashes']=[{k:r[k] for k in ('code','dong_code','year','sha256','checked_at')} for r in responses]
        with tempfile.TemporaryDirectory(prefix='k-apt-stage-') as temp:
            stage=Path(temp)/'project';shutil.copytree(root,stage,ignore=shutil.ignore_patterns('__pycache__'))
            report=run_public(stage,kapt_rows=rows);seoul=read_json(stage/'data/site-data.json');report['gyeonggi']=gg_report
            d,report=merge_data(seoul,gg,report,kapt_report,held)
            html=embedded_html((stage/'index.html').read_text(),d)
            # All source guards and validation above finish before changing the live snapshot.
            publish_bundle(root,d,previous=old,html_source=html)
            metadata=read_json(stage/'data/complexes.json')+cat;atomic_json(root/'data/complexes.json',metadata)
            atomic_json(root/'reports/update-report.json',report)
            atomic_json(root/'reports/coverage.json',coverage_report(d))
        print('서울·경기 전체 업데이트 완료:',report['complex_count'],'개 단지 /',report['trade_count'],'건',flush=True)
        return report
    except (DataError,ValueError,KeyError,TypeError,OSError) as e:
        msg=str(e) if isinstance(e,DataError) else '전체 수집 또는 검증 실패: 이전 정상 자료 유지'
        atomic_json(root/'reports/update-report.json',{'status':'failed','published':False,'finished_at':now(),'error':msg});raise DataError(msg) from None


def coverage_report(d):
    summary=[]
    for region in d['meta']['loaded_regions']:
        cs=[c for c in d['complexes'] if c['region']==region]
        summary.append({'region':region,'complexes':len(cs),'sale_rows':sum(len(c['tx']) for c in cs),'jeonse_rows':sum(len(c.get('jeonse_tx',[])) for c in cs),'far_verified':sum((c.get('far_info') or {}).get('status')=='verified' for c in cs),'unresolved':sum(c.get('data_status')=='matching_unconfirmed' for c in cs)})
    return {'period':d['meta']['min_month']+'~'+d['meta']['current_month'],'regions':summary,'total_complexes':len(d['complexes']),'sale_rows':sum(x['sale_rows'] for x in summary),'jeonse_rows':sum(x['jeonse_rows'] for x in summary),'unresolved_complexes':sum(x['unresolved'] for x in summary)}
