# Frontend Pack UI contract

A product Pack owns domain pages, route keys and local task guards. It does not
own the application shell, tenant navigation, authentication, base capability
mapping, knowledge asset identity or publication state.

Every installed bundle must:

1. declare a unique lowercase `bundleKey`;
2. declare a non-empty, closed `ownedRouteKeys` set prefixed by that key;
3. build routes only when the authenticated server bootstrap supplies the same
   bundle and route key;
4. apply a runtime capability or domain permission guard to every action;
5. use the shared workspace, async, confirmation and lifecycle components;
6. preserve canonical asset/evidence links when opening a specialist viewer;
7. render no route, navigation or action when its Pack is absent or disabled.

`installed.ts` is the build-time composition root. `registry.tsx` validates
bundle ownership at startup and intersects every server manifest with the
bundle's closed route set. Server bootstrap remains authoritative; the browser
registry may remove unsafe or unknown entries but may never add entitlement.
