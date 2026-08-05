import io, sys, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import yaml

LABELS = {
    "scan_01": {
        "title": "文件標題", "company": "客戶公司名稱", "contact": "聯絡人姓名",
        "phone": "聯絡電話", "email": "電子郵件", "order_date": "訂單日期",
        "order_no": "訂單編號", "tax_id": "統一編號", "total": "總計金額",
        "vendor": "廠商（系統提供方）名稱",
    },
    "scan_02": {
        "title": "文件標題", "org": "團體名稱", "supervisor": "指導單位",
        "period": "參與期間", "instagram": "Instagram 帳號",
        "field_student": "學生欄位的標籤文字", "field_parent": "家長欄位的標籤文字",
        "field_parent_phone": "家長聯絡電話欄位的標籤文字",
    },
    "scan_03": {
        "brand": "品牌名稱", "title": "文件類型", "subtitle": "副標題",
        "site": "所屬網站", "version": "軟體版本",
        "chapter_1": "第一章章名", "chapter_2": "第二章章名", "chapter_5": "第五章章名",
    },
    "scan_04": {
        "title": "第一章章名", "chapter_1": "第一篇篇名",
        "principle_1": "第一個基本原則", "principle_2": "第二個基本原則",
        "reference": "引用的教科書作者", "chapter_2": "第二章章名",
    },
    "scan_05": {
        "title": "報告標題", "publisher": "發布媒體",
        "topic_us": "美國段的策略主軸", "topic_china": "中國段的策略主軸",
        "org_ifr": "機器人密度數據的引用機構", "germany_institute": "德國機器人研究機構名稱",
    },
    "scan_06": {
        "title": "文件標題", "form_no": "表單代號", "tax_id": "統一編號",
        "period": "所屬期間", "deadline": "繳納期限", "company": "營業人名稱",
        "responsible": "負責人姓名", "amount": "應納稅額",
    },
    "scan_07": {
        "title": "文件標題", "party_a": "甲方公司", "party_b": "乙方公司",
        "party_a_tax_id": "甲方統一編號", "party_b_tax_id": "乙方統一編號",
        "signed_date": "簽署日期",
    },
    "scan_08": {
        "title": "文件標題", "form_no": "表單代號", "tax_id": "統一編號",
        "period": "所屬期間", "deadline": "繳納期限", "company": "營業人名稱",
        "responsible": "負責人姓名", "amount": "應納稅額",
    },
    "scan_09": {
        "title": "文件標題", "org": "發布組織",
        "section_1_en_gloss": "第一條的英譯標題", "section_2_en_gloss": "第二條的英譯標題",
        "section_4_en_gloss": "第四條的英譯標題",
    },
    "scan_10": {
        "title": "文件標題", "traveler_1_name": "第一位旅客姓名",
        "traveler_1_dob": "第一位旅客出生日期", "traveler_1_passport": "第一位旅客護照號碼",
        "country": "國家/地區", "flight": "入境航班", "arrival_date": "預計入境日",
    },
    "scan_11": {
        "title": "文件標題", "party_a": "甲方", "party_b": "乙方",
        "fee": "服務費用總額", "bank": "匯款銀行",
        "period_start": "合約起始日", "period_end": "合約結束日",
    },
    "scan_12": {
        "title": "文件標題", "field_tax_id": "統一編號欄位的標籤文字",
        "field_invoice_no": "發票號碼欄位的標籤文字", "field_applicant": "立切結書人欄位的標籤文字",
        "company": "立切結書人公司", "responsible": "負責人",
        "counterparty": "對方公司（開立發票方）", "invoice_no": "發票號碼", "amount": "發票總金額",
    },
}

for path in sorted(glob.glob("testdata/golden/z1_scan_annotations/scan_*.yaml")):
    data = yaml.safe_load(open(path, encoding="utf-8"))
    sid = data["id"]
    mapping = LABELS.get(sid, {})
    for fld in data.get("fields") or []:
        label = mapping.get(fld.get("name"))
        if label:
            fld["label"] = label
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    print("labeled", sid, len(mapping))
