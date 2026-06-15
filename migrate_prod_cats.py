#!/usr/bin/env python3
"""Migrate product category tags from 5-class to 8-class system."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PROD_CAT_ORDER = [
    '大模型 / 算法',
    'AI Agent / 应用',
    '芯片 / 算力',
    'AI 基础设施',
    '机器人 / 具身智能',
    '消费电子 / 终端',
    '工业 / 制造',
    '数据 / 云 / 安全',
]

LEGACY = {
    '硬件': ['芯片 / 算力'],
    '软件': ['AI Agent / 应用'],
    '大模型': ['大模型 / 算法'],
    '基础设施': ['AI 基础设施'],
    '机器人': ['机器人 / 具身智能'],
}

CONF_OVERRIDES = {
    'ICLR2024': ['大模型 / 算法'], 'ICLR2025': ['大模型 / 算法'],
    'CVPR2024': ['大模型 / 算法', '工业 / 制造'], 'CVPR2026': ['大模型 / 算法', '工业 / 制造'],
    'ICML2024': ['大模型 / 算法'], 'ICML2026': ['大模型 / 算法'],
    'NeurIPS2024': ['大模型 / 算法'], 'NeurIPS2025': ['大模型 / 算法'], 'NeurIPS2026': ['大模型 / 算法'],
    'AAAI2025': ['大模型 / 算法'], 'AAAI2026': ['大模型 / 算法'],
    'ICRA2024': ['机器人 / 具身智能', '工业 / 制造'], 'ICRA2025': ['机器人 / 具身智能', '工业 / 制造'], 'ICRA2026': ['机器人 / 具身智能', '工业 / 制造'],
    'GTC2025': ['芯片 / 算力'], 'GTC2026': ['芯片 / 算力'], 'GTC2026Berlin': ['芯片 / 算力'],
    'Dreamforce2024': ['AI Agent / 应用'], 'Dreamforce2025': ['AI Agent / 应用'], 'Dreamforce2026': ['AI Agent / 应用'],
    'GCN2024': ['AI Agent / 应用', 'AI 基础设施'], 'GCN2025': ['AI Agent / 应用', 'AI 基础设施'], 'GCN2026': ['AI Agent / 应用', 'AI 基础设施'],
    'MSBuild2024': ['AI Agent / 应用'], 'MSBuild2025': ['AI Agent / 应用'], 'MSBuild2026': ['AI Agent / 应用'],
    'WWDC2024': ['AI Agent / 应用', '消费电子 / 终端'], 'WWDC2025': ['AI Agent / 应用', '消费电子 / 终端'], 'WWDC2026': ['AI Agent / 应用', '消费电子 / 终端'],
    'AWSreInvent2024': ['AI 基础设施', '数据 / 云 / 安全'], 'AWSreInvent2025': ['AI 基础设施', '数据 / 云 / 安全'], 'AWSreInvent2026': ['AI 基础设施', '数据 / 云 / 安全'],
    'CES2025': ['消费电子 / 终端'], 'CES2026': ['消费电子 / 终端'],
    'MWC2024': ['消费电子 / 终端'], 'MWC2025': ['消费电子 / 终端'], 'MWC2026': ['消费电子 / 终端'],
    'MWCShanghai2025': ['消费电子 / 终端'], 'MWCShanghai2026': ['消费电子 / 终端'],
    'IFA2025': ['消费电子 / 终端'],
    'Computex2025': ['芯片 / 算力', '消费电子 / 终端'], 'Computex2026': ['芯片 / 算力', '消费电子 / 终端'],
    'SEMICONWest2025': ['芯片 / 算力'],
    'GITEX2024': ['数据 / 云 / 安全', 'AI Agent / 应用'], 'GITEX2025': ['数据 / 云 / 安全', 'AI Agent / 应用'], 'GITEX2026': ['数据 / 云 / 安全', 'AI Agent / 应用'],
    'WAIC2025': ['大模型 / 算法', '机器人 / 具身智能', 'AI Agent / 应用'], 'WAIC2026': ['大模型 / 算法', '机器人 / 具身智能', 'AI Agent / 应用'],
    'ChinaComputingConf2025': ['芯片 / 算力'], 'ChinaComputingConf2026': ['芯片 / 算力'],
    'WRC2025': ['机器人 / 具身智能'],
    'BAAIConf2025': ['大模型 / 算法'], 'BAAIConf2026': ['大模型 / 算法'],
    'ChinaLLMSummit2025': ['大模型 / 算法'],
    'CCF2025BigData': ['数据 / 云 / 安全'],
    'BigDataExpo2025': ['数据 / 云 / 安全'],
    'ChinaInternetConf2025': ['数据 / 云 / 安全'],
    'IntelligentMfgChina2025': ['工业 / 制造'],
    'HDC2025': ['AI Agent / 应用'],
    'ApsaraConference2025': ['AI Agent / 应用', 'AI 基础设施'],
    'CHTF2025': ['消费电子 / 终端', '工业 / 制造'], 'CHTF2026': ['消费电子 / 终端', '工业 / 制造'],
    'WorldSummitAI2026': ['大模型 / 算法', 'AI Agent / 应用'],
}


def infer_from_text(text):
    p = str(text or '').lower()
    if not p:
        return []
    out = set()
    if re.search(r'llm|大模型|gpt|foundation model|language model|multimodal|扩散|diffusion|强化学习|reinforcement|对齐|alignment|表示学习|neurips|iclr|icml|cvpr|智源|认知|aigc|genai|盘古|星火', p):
        out.add('大模型 / 算法')
    if re.search(r'agent|copilot|saas|enterprise ai|企业ai|开发者|developer|workspace|crm|erp|fintech|应用层|智能体', p):
        out.add('AI Agent / 应用')
    if re.search(r'gpu|芯片|chip|semiconductor|npu|asic|fpga|tpu|算力|compute|semicon|computex|晶圆|代工', p):
        out.add('芯片 / 算力')
    if re.search(r'cloud|云计算|infra|datacenter|数据中心|mlops|vertex|azure|hosting|vector db|ai infra|基础设施', p):
        out.add('AI 基础设施')
    if re.search(r'robot|robotics|humanoid|人形|具身|机器狗|四足|icra|wrc|机器人', p):
        out.add('机器人 / 具身智能')
    if re.search(r'ces|consumer|手机|phone|眼镜|glass|goggle|headset|ai pc|copilot\+pc|wearable|iot|aiot|家电|ifa|mwc|车载|smart home|xr|ar |vr |消费电子|终端', p):
        out.add('消费电子 / 终端')
    if re.search(r'工业|制造|智能制造|工业互联网|manufacturing|industry 4|低空|autonomous driving|self-driving|自动驾驶|adas|感知', p):
        out.add('工业 / 制造')
    if re.search(r'大数据|数据要素|数据湖|data governance|网络安全|cyber|security|安全|治理|gitex|互联网大会|ccpa|privacy', p):
        out.add('数据 / 云 / 安全')
    allowed = set(PROD_CAT_ORDER)
    return [c for c in PROD_CAT_ORDER if c in out]


def migrate_cat_list(cats, text=''):
    merged = set()
    for c in cats or []:
        if c in PROD_CAT_ORDER:
            merged.add(c)
        elif c in LEGACY:
            merged.update(LEGACY[c])
    for c in infer_from_text(text):
        merged.add(c)
    if not merged and cats:
        for c in cats:
            merged.update(LEGACY.get(c, []))
    return [c for c in PROD_CAT_ORDER if c in merged]


def fmt_cats_js(cats):
    inner = ','.join(f"'{c}'" for c in cats)
    return f'[{inner}]'


def migrate_registry():
    path = ROOT / 'exhibitor-data/company-registry.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    n = 0
    for entry in data.values():
        old = entry.get('cats') or []
        text = ' '.join(filter(None, [entry.get('productZh'), entry.get('product'), entry.get('nameZh'), entry.get('nameEn')]))
        new = migrate_cat_list(old, text)
        if new != old:
            entry['cats'] = new
            n += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'company-registry: migrated {n} entries')


def migrate_index_html():
    path = ROOT / 'index.html'
    text = path.read_text(encoding='utf-8')

    # migrate inline cats:[...] arrays
    cat_re = re.compile(r"cats:\[([^\]]*)\]")

    def repl_cat(m):
        inner = m.group(1)
        old = re.findall(r"'([^']*)'", inner)
        if not old:
            return m.group(0)
        new = migrate_cat_list(old)
        if not new:
            return 'cats:[]'
        return 'cats:' + fmt_cats_js(new)

    text, n = cat_re.subn(repl_cat, text)
    print(f'index.html cats arrays: {n} replacements')

    # add productCats to conferences missing it
    block_re = re.compile(r"(id:'([^']+)'[\s\S]*?\n\s*)focus:\[")
    overrides_used = 0

    def repl_conf(m):
        nonlocal overrides_used
        prefix, cid = m.group(1), m.group(2)
        if 'productCats:' in prefix:
            return m.group(0)
        # extract focus block for inference
        start = m.end()
        focus_m = re.match(r"([\s\S]*?\n\s*)\]", text[start:])
        focus_inner = focus_m.group(1) if focus_m else ''
        focus_items = re.findall(r"'([^']*)'", focus_inner)
        blob = ' '.join(focus_items)
        cats = CONF_OVERRIDES.get(cid) or infer_from_text(blob)
        if not cats and cid in CONF_OVERRIDES:
            cats = CONF_OVERRIDES[cid]
        if cats:
            overrides_used += 1
            return prefix + 'productCats:' + fmt_cats_js(cats) + ',\n  focus:['
        return m.group(0)

    text = block_re.sub(repl_conf, text)
    print(f'index.html productCats added: {overrides_used} conferences')

    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    migrate_registry()
    migrate_index_html()
    print('done')
