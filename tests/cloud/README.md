# Cloud verification

The report in reports/v31-cloud-validation.json records local protocol/UI and PostgreSQL checks. No live Supabase project was available during production of this ZIP.

Browser tests use the real bundled Supabase SDK and a mocked Auth/PostgREST/Storage service; tests cover two isolated devices, RLS-style per-user access, conflict responses, offline changes across reload, image byte transfer, guest import and account switching. PostgreSQL execution used PGlite 0.3.14 with auth/storage schema stubs and ran the supplied SQL twice, then checked revision conflicts, row/file account isolation and anon RPC denial.

The final live acceptance check is to log in from two different browsers after setup, change one memo/image title and verify it appears in the other; log in as a second user and verify none of the first user's account notes appear.

To rerun from the project root, use an isolated Node environment with playwright and @electric-sql/pglite installed:

```sh
node tests/cloud/check-protocol.cjs
node tests/cloud/check-sql.cjs
```

The browser test uses Playwright Chromium, or a local executable supplied by KAPT_TEST_BROWSER. Playwright needs its Chromium installed. PGlite 0.3.14 was used for the reported SQL checks. Test accounts, project URL and API key in the browser test are mock fixtures only. No real credentials are stored.
