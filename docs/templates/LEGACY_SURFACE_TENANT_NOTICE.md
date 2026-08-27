# Enclave compatibility migration notice template

**Tenant:** `<tenant name / id>`
**Notice owner:** `<name>`
**Notice date:** `<UTC date>`
**Earliest possible disable date:** `<not earlier than the registry gate>`

Enclave is consolidating the compatibility surface `<deprecation key>` into
`<replacement path>`. The current path continues to operate during the observe
and warn periods. This notice does not authorize deletion of tenant data.

## Action requested

- Update bookmarks, scripts or SDK calls to `<replacement path>`.
- Return the client version and planned migration date to the notice owner.
- Report any workflow that cannot use the successor, including expected user
  role, evidence type and output contract. Do not send credentials or source
  content in the response.

## Safety and schedule

The compatibility surface can be disabled only after every active tenant has a
complete 30-day zero-traffic window, telemetry health has been confirmed, and a
signed all-tenant report says `ELIGIBLE`. Any new hit restarts that surface's
window. Rollback keeps original objects and database backups; removal and data
deletion are separate changes.

**Tenant acknowledgement:** `<name / date / decision>`
**Support contact:** `<channel>`
