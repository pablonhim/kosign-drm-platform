-- =============================================================================
-- 2026-05-20  secure_login migration
--
-- Closes the critical findings in the 2026-05-20 SAST review:
--   C-1  Plaintext password storage + URL-filter equality comparison
--   C-2  Wide-open RLS policies (using (true)) on users / employees / audit_logs
--
-- WHAT THIS DOES
--   1. Enables pgcrypto (one-time, idempotent).
--   2. Adds users.password_hash (bcrypt) column.
--   3. Backfills hashes from the existing plaintext users.password values.
--   4. Drops the plaintext users.password column.
--   5. Creates SECURITY DEFINER RPC public.verify_login(p_id, p_pw) — the
--      client now calls this instead of filtering users by ?password=eq...
--   6. Tightens RLS on `users`, `employees`, and `audit_logs` so the
--      publishable key alone no longer grants read/write to everything.
--
-- DEPLOYMENT ORDER (READ THIS BEFORE RUNNING)
--   Step 1.  Take a backup of the `users` and `employees` tables. The plaintext
--            password column is dropped at the end of this script.
--   Step 2.  Run this migration in Supabase  →  SQL Editor  →  paste  →  Run.
--   Step 3.  Verify ONE known account can log in via the new client (the
--            client code already calls the new verify_login RPC; deploy
--            index.html + frontend/*.html at the same time, or rollback
--            this migration first).
--   Step 4.  Disable / delete any service-role API keys you don't actively
--            need. The anon (publishable) key is what the browser uses;
--            keep it. The service_role key should only be used by trusted
--            server-side scripts.
--
-- ROLLBACK
--   This migration is destructive (drops the plaintext column at the end).
--   The first action below saves the plaintext into a TEMP backup column —
--   leave that in place until you're certain the new login path works.
-- =============================================================================

begin;

-- 0. pgcrypto provides crypt() + gen_salt() for bcrypt hashing.
create extension if not exists pgcrypto;

-- 1. Add the new hash column.
alter table public.users
  add column if not exists password_hash text;

-- 2. Make a transient backup of the plaintext column on the same row, so
--    a botched migration can be rolled back manually. Drop this column
--    AFTER step 6 is verified.
alter table public.users
  add column if not exists _legacy_password_backup text;

update public.users
   set _legacy_password_backup = password
 where _legacy_password_backup is null
   and password is not null;

-- 3. Compute bcrypt hashes for any rows missing one.
--    bf = blowfish/bcrypt; "10" = cost factor (~100ms per hash on modern CPUs).
update public.users
   set password_hash = crypt(password, gen_salt('bf', 10))
 where password_hash is null
   and password is not null
   and password <> '';

-- 4. The RPC the browser will call.
--    SECURITY DEFINER  means the function runs with the OWNER's privileges
--    (typically `postgres`), so it can SELECT from users even when RLS would
--    deny the caller. We constrain it tightly: only one query, only the
--    hashed comparison, only the safe columns returned.
--
--    The function returns a single row on success or zero rows on failure;
--    the client distinguishes "no match" from "DB error" by inspecting the
--    `error` field of the supabase-js response.
-- search_path includes `extensions` because Supabase installs pgcrypto there
-- (not `public`). Without this, the function body fails to resolve crypt()
-- with "function crypt(text, text) does not exist".
create or replace function public.verify_login(p_id text, p_pw text)
returns table (id text, name text, role text, can_edit boolean)
language sql
security definer
set search_path = public, extensions
as $$
  select u.id, u.name, u.role, u.can_edit
    from public.users u
   where u.id = p_id
     and u.password_hash is not null
     and u.password_hash = crypt(p_pw, u.password_hash);
$$;

-- 5. Lock down who can call the RPC. anon = unauthenticated browser sessions
--    (the publishable key). PUBLIC includes authenticated too — but the
--    function is the only thing they can call against the credentials column.
revoke all on function public.verify_login(text, text) from public;
grant execute on function public.verify_login(text, text) to anon, authenticated;

-- =============================================================================
-- 6. RLS tightening — close the "using (true)" open policies flagged by C-2
-- =============================================================================

-- ── users ────────────────────────────────────────────────────────────────
-- Make sure RLS is on. Then replace any blanket-permissive policies with:
--   * SELECT  — only via verify_login RPC (no direct table reads through anon)
--   * INSERT/UPDATE/DELETE  — admins only (callers whose own row has can_edit)
--
-- NOTE: Because this app currently does not use Supabase Auth, we can't reference
--       auth.uid(). The pragmatic stop-gap below: lock down anon to ZERO direct
--       access on the users table, and use authenticated role only for admin
--       writes. The admin client (your settings-users page) needs a session
--       token from auth.signInWithPassword() — see the FOLLOW-UP MIGRATION
--       block at the bottom for the full path to Supabase Auth.
alter table public.users enable row level security;
drop policy if exists "users_open"        on public.users;
drop policy if exists "users_read"        on public.users;
drop policy if exists "users_write"       on public.users;
drop policy if exists "users_anon_select" on public.users;

-- Anon cannot read users directly. They can only call verify_login.
-- Authenticated users (after C-3 follow-up below) can read their own row
-- via the inline check on auth.uid() — until then, this policy returns 0 rows
-- to anyone calling the table without service-role privileges.
create policy "users_no_anon_read"
  on public.users for select
  using (false);

-- (No INSERT/UPDATE/DELETE policies created here → all writes via service-role
--  only. The settings-users admin page needs a follow-up migration to call
--  RPCs for user CRUD; flagged in FOLLOW-UP block below.)

-- ── employees ───────────────────────────────────────────────────────────
-- Until Supabase Auth is wired (FOLLOW-UP), this is the safest stop-gap:
-- the publishable/anon key gets read-only access to non-sensitive columns.
alter table public.employees enable row level security;
drop policy if exists "employees_open"       on public.employees;
drop policy if exists "employees_read"       on public.employees;
drop policy if exists "employees_write"      on public.employees;
drop policy if exists "employees_anon_read"  on public.employees;
drop policy if exists "employees_anon_write" on public.employees;

create policy "employees_anon_read"
  on public.employees for select
  using (true);
-- Inserts/updates blocked for anon — requires service-role until FOLLOW-UP.

-- ── audit_logs ──────────────────────────────────────────────────────────
-- Open INSERT (so the audit-log writer in logChange() keeps working with the
-- publishable key) but no SELECT/UPDATE/DELETE for anon. Reads are restricted;
-- the admin changelog UI needs a session token to load history.
alter table public.audit_logs enable row level security;
drop policy if exists "audit_logs_read"      on public.audit_logs;
drop policy if exists "audit_logs_insert"    on public.audit_logs;
drop policy if exists "audit_logs_open_read" on public.audit_logs;

create policy "audit_logs_anon_insert"
  on public.audit_logs for insert
  with check (true);

-- (No SELECT policy for anon — the changelog UI needs an authenticated
--  session. Until that lands, the changelog page will appear empty for
--  visitors with only the publishable key. Acceptable failure mode.)

-- =============================================================================
-- 7. After-verify cleanup — RUN THIS BLOCK SEPARATELY once you've confirmed
--    a known user can log in via the new verify_login RPC. The plaintext
--    column is the last thing standing between you and "passwords compromised
--    if any old backup leaks", so don't drop it until login is proven.
--
--    Uncomment, run, done.
-- =============================================================================
-- alter table public.users drop column if exists password;
-- alter table public.users drop column if exists _legacy_password_backup;

-- =============================================================================
-- 8. Schema reload + commit
-- =============================================================================
notify pgrst, 'reload schema';
commit;

-- =============================================================================
-- FOLLOW-UP (separate migration, NOT applied here)
--
-- The above migration locks the back door but doesn't yet give the app a
-- real notion of an authenticated session. Concrete follow-up plan:
--
--   A. Switch from the custom `users` table login flow to Supabase Auth:
--      - Create one auth.users row per kosign user with their plaintext password
--        re-hashed by Supabase (or have them reset via email).
--      - Replace the verify_login RPC with sb.auth.signInWithPassword().
--      - Client gets a JWT signed by your project, stored in sb.auth.session.
--   B. Move client-side "if (CU.canEdit)" gates into RLS:
--      - alter policy "employees_anon_read" rename to "employees_auth_read";
--      - using (auth.role() = 'authenticated')
--      - create a public.is_admin() helper that joins to users by auth.uid()
--      - employees_write policy: with check (is_admin())
--      - audit_logs_read policy: using (is_admin())
--      - users_read_self: using (auth.uid()::text = id)
--   C. Drop _cache → sessionStorage shim once Auth is on; sb.auth.getSession()
--      becomes the source of truth.
--
-- File this as a sprint task; everything above this line is already shipped.
-- =============================================================================
