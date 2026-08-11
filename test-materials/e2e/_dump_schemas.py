"""從運行中的 API 擷取 E2E 需要的請求 schema。"""
import json
import urllib.request

spec = json.load(urllib.request.urlopen("http://127.0.0.1:8005/api/v1/openapi.json"))
schemas = spec["components"]["schemas"]

NAMES = [
    "ChatRequest", "FormCreateRequest", "SceneUpsertRequest", "ExtractBody",
    "JobRoleCreate", "AssignmentCreate", "KnowhowCreateRequest",
    "ApprovalDecisionRequest", "FormExportRequest", "EventCreate",
    "SceneResolveRequest", "Body_upload_document_api_v1_documents_upload_post",
    "Body_upload_template_api_v1_forms_templates_post",
    "KnowhowUpdateRequest", "MappingUpdate", "TemplateMappingUpdate",
]

for name in NAMES:
    if name not in schemas:
        print(f"{name}: NOT FOUND")
        continue
    s = schemas[name]
    props = {}
    for k, v in s.get("properties", {}).items():
        t = v.get("type") or ("anyOf" if "anyOf" in v else v.get("$ref", "?"))
        props[k] = t
    print(f"{name} | required: {s.get('required')} | props: {json.dumps(props, ensure_ascii=False)}")
    print()

# 也列出 upload 端點的 request body 形式
for path in ["/api/v1/documents/upload", "/api/v1/forms/templates", "/api/v1/scene/resolve",
             "/api/v1/knowhow", "/api/v1/approvals/{approval_id}/approve",
             "/api/v1/forms/instances/{instance_id}/export",
             "/api/v1/chat/chat", "/api/v1/job-roles/assignments"]:
    p = spec["paths"].get(path, {})
    for method, op in p.items():
        rb = op.get("requestBody", {}).get("content", {})
        kinds = {ct: (c.get("schema", {}).get("$ref") or c.get("schema", {}).get("type")) for ct, c in rb.items()}
        print(f"{method.upper()} {path} -> {kinds}")
