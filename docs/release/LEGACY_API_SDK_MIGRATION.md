# Legacy API and SDK migration

## Response contract

Only registered compatibility APIs return deprecation metadata. Stable v1 APIs
continue to return `X-API-Version: v1` without being falsely marked deprecated.

Legacy responses include:

```http
Deprecation: true
Link: </api/v1/knowledge/assets>; rel="successor-version"
X-Enclave-Deprecation-Key: api.documents
X-Enclave-Deprecation-Stage: observe
```

During `warn`, responses also include an HTTP-date `Sunset` header and RFC 7234
warning. During `disable`, the compatibility path returns `410 Gone` with its
replacement. A client must not infer a removal date while the stage is
`observe`.

## Client mapping

| Compatibility surface | Successor | Required client change |
|---|---|---|
| `/api/v1/documents/**` | `/api/v1/knowledge/assets/**` | Use SourceAsset identity, revision/job lifecycle and asset status. |
| `/api/v1/voice/**` | `/api/v1/knowledge/assets` | Submit durable audio/capture input through unified intake; retain the old session API only for an announced compatibility workflow. |
| `/api/v1/media/videos/**` and `/api/v1/media/video-artifacts/**` | `/api/v1/knowledge/assets/**`, `/api/v1/knowledge/review-items/**` | Use the asset detail, typed evidence locator and unified decision contract. The specialized timeline remains available throughout observe. |
| `/api/v1/agent/review/**` | `/api/v1/knowledge/review-items/**` | Replace legacy file-classification queue calls with the provider-neutral inbox. |
| `/api/v1/knowledge-captures/**` | `/api/v1/knowledge/assets/**` | Create a capture manifest through unified intake and poll the canonical ingestion job. |
| `/api/v1/knowhow/**` | `/api/v1/knowledge/review-items/**` plus published KnowledgeUnits | Keep domain authoring in the MKA pack; read/review through canonical authority. |
| `/api/v1/job-modules/**` | `/api/v1/experience/bootstrap` capability catalog | Read four-dimensional capability state from bootstrap; pack administration remains pack-owned until its announced successor is available. |

## SDK behavior

1. Log `X-Enclave-Deprecation-Key` with tenant/client version, without request
   payloads or credentials.
2. Follow the `Link` successor relation; never construct a successor by string
   replacement.
3. Treat `410` as a permanent compatibility-path failure and present the
   replacement path.
4. Do not suppress tenant ACL, evidence, review or release checks while adapting
   old response objects.
5. Roll out the client before requesting a server surface to move from
   `observe` to `warn`.

## Verification checklist

- No legacy key is observed in client integration logs for 30 complete days.
- The server signed report includes every active tenant and says `ELIGIBLE`.
- Bookmark redirects and the successor APIs pass in the same release candidate.
- SDK retry/idempotency tests cover both the final compatibility release and the
  successor API.
